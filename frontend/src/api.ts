/**
 * The one client this API has.
 *
 * Every path is relative: in development the Vite dev server proxies them to
 * the API, and in the container the API serves this bundle itself.
 *
 * One call here carries the PIN, and exactly one: clearing a miss. Everything
 * else this screen writes — claiming, and marking a chore missed — is a
 * proposal rather than money, and needs no credential for the same reason: it
 * pays nothing, and settlement is what pays. Clearing is the direction that
 * gives money back, so it is the direction that asks. See
 * app/routers/claims.py, which states the rule and enforces it server-side;
 * nothing on this side is what makes it true.
 */

export type InstanceCard = {
  instance_id: number | null
  definition_id: number
  name: string
  category: 'basic' | 'bonus' | 'reward'
  cadence: string
  amount_pence: number
  state: 'untouched' | 'claimed' | 'confirmed' | 'missed'
  sequence: number
  due_date: string | null
  can_claim: boolean
  rejection_count: number
  miss_origin: string | null
}

export type DayCard = {
  day: string
  weekday: string
  is_today: boolean
  is_past: boolean
  waived: boolean
  waiver_reason: string | null
  chores: InstanceCard[]
}

export type WeeklyCard = {
  definition_id: number
  name: string
  category: 'basic' | 'bonus' | 'reward'
  cadence: string
  amount_pence: number
  required: number
  confirmed: number
  claimed: number
  instances: InstanceCard[]
  judged_at_settlement: boolean
  waived: boolean
}

export type RecoveryNeed = {
  definition_id: number
  miss_name: string
  covered_by: string | null
}

/** The way back from a miss, worked out by the engine and not by this screen:
 *  which bonus chores to do, and what the week is worth once they are. Null
 *  whenever there is no route — which renders as nothing at all. */
export type MakeGood = {
  names: string[]
  restores_to_pence: number
}

export type RecoveryPanel = {
  needs: RecoveryNeed[]
  outstanding: number
  covered: number
  cap: number
  deadline: string
  seconds_remaining: number
  days_remaining: number
  urgent: boolean
  options: InstanceCard[]
  spent: InstanceCard[]
  make_good: MakeGood | null
}

export type Totals = {
  base_pence: number
  chore_pay_at_stake_pence: number
  chore_pay_pence: number
  chore_pay_awarded: boolean
  bonus_pence: number
  /** Rewards from REWARD-category chores, which settle with the week. */
  reward_pence: number
  /** Rewards a parent entered, which are owed on top of the settled figure. */
  ad_hoc_reward_pence: number
  /** Bonus money given up, unpaid, to cover a miss — already absent from
   * bonus_pence. Carried separately so a completed bonus chore does not just
   * vanish from the screen; see recovery.spent for which chore it was. */
  held_as_makegood_pence: number
  total_pence: number
  /** What he will actually be handed for this week: the two added up. */
  payable_total_pence: number
}

export type WeekView = {
  child_name: string
  week_id: number
  start_date: string
  end_date: string
  status: string
  today: string
  /** False for a past week read while paging back through history. */
  is_current: boolean
  days: DayCard[]
  weekly: WeeklyCard[]
  waived_days: string[]
  recovery: RecoveryPanel
  totals: Totals
}

export type SavingsBalance = { balance_pence: number }

export type Depositors = { child_name: string; parent_names: string[] }

export type DepositRequestState = 'pending' | 'confirmed' | 'rejected'

/** A deposit Oliver has proposed — pending until a parent confirms it with
 * the PIN, the same wait a claimed chore sits in. */
export type DepositRequest = {
  id: number
  amount_pence: number
  note: string
  posted_by: string
  occurred_on: string
  state: DepositRequestState
  submitted_at: string
  decided_at: string | null
  decided_by: string | null
}

/** What the next unsettled month is worth, whether or not it has finished
 * yet — see app.services.savings_match.propose. `month_has_ended` is what
 * tells a live, still-moving preview apart from a final, settled figure. */
export type SavingsMatchProposal = {
  period_start: string
  period_end: string
  balance_low_pence: number
  had_withdrawal: boolean
  rate_percent: number
  cap_pence: number
  match_pence: number
  month_has_ended: boolean
  clean_months_in_a_row: number
}

export type BalancePoint = { occurred_on: string; balance_pence: number }

/** Everything ever earned, and the two savings trajectories — the real one
 * and, if no withdrawal had ever happened, what it would be instead. See
 * app.services.lifetime: the counterfactual is framed as "how money grows
 * if you leave it alone", never as "what you would have had". */
export type Lifetime = {
  total_earned_pence: number
  real: BalancePoint[]
  counterfactual: BalancePoint[]
}

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `The app returned ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      /* a response with no JSON body: the status is all there is to say */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

/**
 * Open this week if it is not open yet, and load it.
 *
 * Idempotent by design on the server, so the screen calls it on every load
 * rather than having to know whether anything has happened this week.
 */
export async function loadWeek(): Promise<WeekView> {
  return json<WeekView>(await fetch('/api/week/open', { method: 'POST' }))
}

export type WeekSummary = {
  week_id: number
  start_date: string
  end_date: string
  status: 'open' | 'settled' | 'voided'
  total_pence: number | null
}

/** Every week that exists as a row, oldest first — what paging back reads
 * to know which weeks it can actually go to. Needs no credential. */
export async function loadWeeks(): Promise<WeekSummary[]> {
  return json<WeekSummary[]>(await fetch('/api/weeks'))
}

/** Any week, open or closed, in the same shape — read-only once closed.
 * Used to page back to a week that is not the one currently open. */
export async function loadWeekById(weekId: number): Promise<WeekView> {
  return json<WeekView>(await fetch(`/api/week/${weekId}`))
}

/** What's in the account. Read-only, needs no credential — the same as
 * every other GET on this screen. */
export async function loadSavingsBalance(): Promise<SavingsBalance> {
  return json<SavingsBalance>(await fetch('/api/savings'))
}

/** May reject — a 409 when the savings ledger has no entries at all yet.
 * That is a real state ("nothing to match"), not a failure, so the savings
 * screen catches it rather than treating it as an error to display. */
export async function loadSavingsMatchProposal(): Promise<SavingsMatchProposal> {
  return json<SavingsMatchProposal>(await fetch('/api/savings/match/proposal'))
}

/** Who a deposit's "posted by" may name. Read-only, needs no credential. */
export async function loadDepositors(): Promise<Depositors> {
  return json<Depositors>(await fetch('/api/savings/deposits/depositors'))
}

/** Oliver's own deposits still waiting on a parent. */
export async function loadMyPendingDeposits(childName: string): Promise<DepositRequest[]> {
  const all = await json<DepositRequest[]>(await fetch('/api/savings/deposits/pending'))
  return all.filter((request) => request.posted_by === childName)
}

/**
 * Propose a deposit. No PIN — see markMissed's own note on why: this moves
 * no money by itself, and waits for a parent the same way a claim does.
 */
export async function submitDeposit(
  amountPence: number,
  note: string,
  postedBy: string,
): Promise<DepositRequest> {
  return json<DepositRequest>(
    await fetch('/api/savings/deposits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount_pence: amountPence, note, posted_by: postedBy }),
    }),
  )
}

/** Never rejects — an account with no history at all reads as all-zero and
 * empty trajectories, not an error. */
export async function loadLifetime(): Promise<Lifetime> {
  return json<Lifetime>(await fetch('/api/lifetime'))
}

export async function claim(instanceId: number): Promise<void> {
  await post('/api/claims', { instance_id: instanceId })
}

/**
 * Mark a chore missed. No PIN, deliberately.
 *
 * A parent standing at the sink has about ten seconds to record that
 * yesterday was missed, and four digits on a wall screen is long enough to
 * lose that. It pays nothing and takes nothing: it proposes a miss, the way a
 * claim proposes work, and settlement is where either turns into money.
 */
export async function markMissed(instanceId: number): Promise<void> {
  await post(`/api/instances/${instanceId}/missed`, { instance_id: instanceId })
}

/**
 * Take that mark back. This one asks for the PIN.
 *
 * The asymmetry is the point: anything that costs him money is a tap, and
 * anything that gives it back is a parent. The PIN goes nowhere but into this
 * one request — see PinDialog, which holds it for the length of the call and
 * is unmounted afterwards.
 */
export async function clearMiss(pin: string, instanceId: number): Promise<void> {
  await post(`/api/instances/${instanceId}/missed/clear`, {
    pin,
    instance_id: instanceId,
  })
}

async function post(path: string, body: unknown): Promise<void> {
  await json<unknown>(
    await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  )
}

/**
 * Pence, written the way the amount would be said out loud.
 *
 * 40 -> "40p", 100 -> "£1", 450 -> "£4.50". Nobody in this house says "nought
 * point four zero pounds", and the child reading this screen is being taught
 * what money is worth, so the screen writes it the way he will hear it.
 */
export function money(pence: number): string {
  if (pence === 0) return '£0'
  if (pence < 100) return `${pence}p`
  const pounds = Math.trunc(pence / 100)
  const remainder = pence % 100
  if (remainder === 0) return `£${pounds}`
  return `£${pounds}.${String(remainder).padStart(2, '0')}`
}

/**
 * Pounds as typed by a person, to integer pence. Null if it is not a number.
 *
 * Deliberately no `parseFloat`. The rule in this project is that no floating
 * point touches currency anywhere, and it is not suspended because this side
 * is TypeScript: 4.35 is not representable, and `Math.round(4.35 * 100)` is
 * 435 only because the error happens to fall the right way. This splits the
 * string and does integer arithmetic, so "4.35" is 435 by construction.
 *
 * A third decimal is refused rather than rounded, matching the API's own
 * parser: an amount that cannot be paid in coins is a typing mistake, not a
 * value to guess at.
 */
export function parsePence(text: string): number | null {
  const cleaned = text.trim().replace(/^£/, '').replace(/,/g, '')
  if (cleaned === '') return null

  const asPence = cleaned.match(/^(\d+)p$/)
  if (asPence) return Number(asPence[1])

  const match = cleaned.match(/^(\d*)(?:\.(\d{1,2}))?$/)
  if (!match) return null
  const [, pounds, decimals] = match
  if (!pounds && !decimals) return null

  return Number(pounds || '0') * 100 + Number((decimals ?? '').padEnd(2, '0'))
}
