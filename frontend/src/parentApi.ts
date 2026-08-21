/**
 * The parent's half of the API.
 *
 * Every call that changes anything takes a PIN as an argument rather than
 * reading one from anywhere. There is no module-level PIN, no store holding
 * one, and nothing that could keep one alive between two calls: the value
 * arrives from the dialog that collected it, is put in one request body, and
 * goes out of scope when the call returns.
 *
 * That is the whole mechanism. The API refuses these requests server-side
 * without a correct PIN, so nothing here is a security control — it is about
 * not leaving a credential lying around a screen the child also uses.
 */

import type { WeekView } from './api'

export type Pending = {
  instance_id: number
  definition_id: number
  name: string
  category: 'basic' | 'bonus' | 'reward'
  cadence: string
  amount_pence: number
  sequence: number
  due_date: string | null
  week_id: number
  week_start_date: string
  claimed_at: string | null
  rejection_count: number
}

export type Ruling = 'confirm' | 'reject'

export type DecisionIn = { instance_id: number; decision: Ruling }

export type Figures = {
  misses: number
  misses_outstanding: number
  recoveries: string[][]
  chore_pay_awarded: boolean
  chore_pay_at_stake_pence: number
  chore_pay_pence: number
  bonus_pence: number
  reward_pence: number
  total_pence: number
}

export type Consequence = {
  week_id: number
  start_date: string
  end_date: string
  confirmed: number
  rejected: number
  before: Figures
  after: Figures
  difference_pence: number
  rescues_the_chore_pay: boolean
  loses_the_chore_pay: boolean
}

export type WeekSummary = {
  week_id: number
  start_date: string
  end_date: string
  status: 'open' | 'settled' | 'voided'
  total_pence: number | null
}

export type SettledWeek = {
  week_id: number
  start_date: string
  end_date: string
  status: string
  overridden_by: string | null
  override_reason: string | null
  optimum_total_pence: number | null
  base_pence: number | null
  chore_pay_pence: number | null
  bonus_pence: number | null
  reward_pence: number | null
  total_pence: number | null
  closed_at: string | null
  void_reason: string | null
  paid_at: string | null
  deposited_pence: number | null
  lines: {
    chore_name: string
    category: string
    unit_amount_pence: number
    quantity: number
    amount_pence: number
    note: string | null
  }[]
}

export type Owed = {
  week_id: number
  start_date: string
  end_date: string
  settled_total_pence: number
  reward_pence: number
  owed_pence: number
  is_paid: boolean
}

export type SavingsEntry = {
  id: number
  entry_type: string
  amount_pence: number
  balance_after_pence: number
  occurred_on: string
  week_id: number | null
  reason: string | null
}

export type Savings = { balance_pence: number; entries: SavingsEntry[] }

export type Reconciliation = {
  recorded_balance_pence: number
  actual_balance_pence: number
  difference_pence: number
  agrees: boolean
  put_right_by: string | null
}

export type Waiver = {
  id: number
  scope: string
  day: string | null
  week_id: number | null
  definition_id: number | null
  definition_name: string | null
  reason: string | null
  instances_removed: number
}

export type Preset = {
  key: string
  name: string
  amount_pence: number
  amount: string
}

export type Cadence =
  | 'daily'
  | 'weekdays'
  | 'weekly_count'
  | 'weekly_condition'
  | 'one_off'
  | 'event'

/** date.weekday() order (Monday-first) — matches the server's WEEKDAY_TOKENS. */
export type Weekday =
  | 'monday'
  | 'tuesday'
  | 'wednesday'
  | 'thursday'
  | 'friday'
  | 'saturday'
  | 'sunday'

export const WEEKDAYS: Weekday[] = [
  'monday',
  'tuesday',
  'wednesday',
  'thursday',
  'friday',
  'saturday',
  'sunday',
]

export type ChoreDefinition = {
  id: number
  name: string
  category: 'basic' | 'bonus' | 'reward'
  cadence: Cadence
  times_per_week: number | null
  weekdays: Weekday[] | null
  amount_pence: number
  is_administered: boolean
  is_available: boolean
}

/** What create and edit both send — the rule, without the id or the PIN. */
export type ChoreWrite = {
  name: string
  category: string
  cadence: string
  times_per_week: number | null
  weekdays: string[] | null
  amount_pence: number
  is_administered: boolean
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `The app returned ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) {
        detail =
          typeof body.detail === 'string'
            ? body.detail
            : // A pydantic validation error: the first message is the useful one.
              (body.detail[0]?.msg ?? detail)
      }
    } catch {
      /* no JSON body; the status is all there is to say */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

const get = async <T>(path: string): Promise<T> => json<T>(await fetch(path))

const send = async <T>(path: string, body: unknown): Promise<T> =>
  json<T>(
    await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )

// --- Reading. None of this needs a credential. -----------------------------

export const loadQueue = () => get<Pending[]>('/api/parent/queue')
export const loadWeeks = () => get<WeekSummary[]>('/api/weeks')
export const loadWeek = (id: number) => get<SettledWeek>(`/api/weeks/${id}`)
export const loadOwed = () => get<Owed[]>('/api/weeks/owed/outstanding')
export const loadSavings = () => get<Savings>('/api/savings')
export const loadWaivers = () => get<Waiver[]>('/api/waivers')
export const loadPresets = () => get<Preset[]>('/api/rewards/presets')
export const loadCurrentWeek = () => get<WeekView>('/api/week')
export const loadChores = () => get<ChoreDefinition[]>('/api/chores')

/** What a batch would do. Applies nothing, so it carries no PIN. */
export const previewReview = (decisions: DecisionIn[]) =>
  send<Consequence[]>('/api/parent/review/preview', { decisions })

/** What the account really holds, against what the ledger says. Records nothing. */
export const reconcile = (actual_balance_pence: number) =>
  send<Reconciliation>('/api/savings/reconcile', { actual_balance_pence })

// --- Acts. Each takes the PIN for that one submission. ---------------------

export const submitReview = (pin: string, decisions: DecisionIn[]) =>
  send<{ confirmed: number[]; rejected: number[] }>('/api/claims/review', {
    pin,
    decisions,
  })

export const markMissed = (pin: string, instanceId: number, note?: string) =>
  send<unknown>(`/api/instances/${instanceId}/missed`, {
    pin,
    instance_id: instanceId,
    note: note || null,
  })

export const waiveDay = (pin: string, day: string, reason: string) =>
  send<Waiver>('/api/waivers', { pin, scope: 'day', day, reason })

export const waiveChoreWeek = (
  pin: string,
  weekId: number,
  definitionId: number,
  reason: string,
) =>
  send<Waiver>('/api/waivers', {
    pin,
    scope: 'chore_week',
    week_id: weekId,
    definition_id: definitionId,
    reason,
  })

export const settleWeek = (pin: string, weekId: number, agreed: number) =>
  send<SettledWeek>(`/api/weeks/${weekId}/settle`, {
    pin,
    agreed_total_pence: agreed,
  })

export const voidWeek = (pin: string, weekId: number, reason: string) =>
  send<SettledWeek>(`/api/weeks/${weekId}/void`, { pin, reason })

export const recordReward = (pin: string, amount: string, reason: string) =>
  send<unknown>('/api/rewards', { pin, amount, reason })

export const recordPreset = (pin: string, key: string) =>
  send<unknown>(`/api/rewards/presets/${key}`, { pin })

export const payWeeks = (pin: string, weekIds: number[], deposited: number) =>
  send<{
    paid_pence: number
    deposited_pence: number
    kept_pence: number
    savings_balance_pence: number
  }>('/api/weeks/payments', {
    pin,
    week_ids: weekIds,
    deposited_pence: deposited,
  })

export const recordWithdrawal = (pin: string, amount: number, reason: string) =>
  send<SavingsEntry>('/api/savings/withdrawals', {
    pin,
    amount_pence: amount,
    reason,
  })

export const recordOpeningBalance = (pin: string, amount: number) =>
  send<SavingsEntry>('/api/savings/opening-balance', {
    pin,
    amount_pence: amount,
  })

export const createChore = (pin: string, chore: ChoreWrite) =>
  send<ChoreDefinition>('/api/chores', { pin, ...chore })

export const editChore = (pin: string, id: number, chore: ChoreWrite) =>
  send<ChoreDefinition>(`/api/chores/${id}`, { pin, ...chore })

export const retireChore = (pin: string, id: number) =>
  send<ChoreDefinition>(`/api/chores/${id}/retire`, { pin })
