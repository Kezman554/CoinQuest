/**
 * The one client this API has.
 *
 * Every path is relative: in development the Vite dev server proxies them to
 * the API, and in the container the API serves this bundle itself. Nothing
 * here carries the PIN — this screen is the child's, and the only thing it
 * writes is a claim, which needs no credential because a claim is a request
 * to be believed rather than an assertion that money is owed.
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
}

export type Totals = {
  base_pence: number
  chore_pay_at_stake_pence: number
  chore_pay_pence: number
  chore_pay_awarded: boolean
  bonus_pence: number
  reward_pence: number
  total_pence: number
}

export type WeekView = {
  child_name: string
  week_id: number
  start_date: string
  end_date: string
  status: string
  today: string
  days: DayCard[]
  weekly: WeeklyCard[]
  waived_days: string[]
  recovery: RecoveryPanel
  totals: Totals
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

export async function claim(instanceId: number): Promise<void> {
  await json<unknown>(
    await fetch('/api/claims', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instance_id: instanceId }),
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
