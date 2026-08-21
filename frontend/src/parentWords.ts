/**
 * Saying what a batch does, in the week's terms rather than the list's.
 *
 * "7 items" is a fact about the screen. A parent about to authorise something
 * permanent needs a fact about the week: whether the chore pay comes back or
 * goes, what happens to the misses, which bonus chore is about to be spent
 * covering one, and what the week is worth before and after. The count of
 * ticks tells them none of that, and it is the only thing a naive summary
 * would say.
 *
 * Every sentence here is built from the figures the API computed by actually
 * applying the batch and rolling it back — so this module phrases a
 * consequence and never calculates one. If it were doing arithmetic of its
 * own, the sentence and the outcome could disagree, which is the one failure
 * this whole design exists to rule out.
 */

import { money } from './api'
import type { Cadence, Consequence, Figures, Pending, Weekday } from './parentApi'
import { list, plural, shortDate } from './words'

export function weekLabel(start: string, end: string): string {
  return `${shortDate(start)} – ${shortDate(end)}`
}

/** "3 claims", "1 claim" — never "1 claims". */
function claims(count: number): string {
  return `${count} ${plural(count, 'claim', 'claims')}`
}

/** What the batch is, as an act: what is being agreed and what refused. */
export function batchAction(confirmed: number, rejected: number): string {
  const parts: string[] = []
  if (confirmed) parts.push(`Confirming ${claims(confirmed)}`)
  if (rejected) parts.push(`refusing ${claims(rejected)}`)
  if (parts.length === 0) return 'Nothing to submit'
  return parts.join(' and ')
}

function misses(count: number): string {
  if (count === 0) return 'no misses'
  return `${count} ${plural(count, 'miss', 'misses')}`
}

/** The recoveries in `after` that were not already in `before`. */
function newRecoveries(before: Figures, after: Figures): string[] {
  const had = before.recoveries.map((pair) => pair.join('→'))
  return after.recoveries
    .filter((pair) => !had.includes(pair.join('→')))
    .map(([miss, spent]) => `${spent} is spent covering ${miss}`)
}

function lostRecoveries(before: Figures, after: Figures): string[] {
  const keeps = after.recoveries.map((pair) => pair.join('→'))
  return before.recoveries
    .filter((pair) => !keeps.includes(pair.join('→')))
    .map(([miss, spent]) => `${spent} is no longer spent on ${miss}`)
}

/**
 * The consequence, as sentences a parent can check against the week.
 *
 * Returned as a list rather than a paragraph because they are separate claims
 * and one of them may be the one that stops somebody: a batch that takes the
 * chore pay away should not have that fact buried mid-sentence.
 */
export function consequenceLines(effect: Consequence): string[] {
  const lines: string[] = []
  const { before, after } = effect

  if (effect.rescues_the_chore_pay) {
    lines.push(
      `The chore money comes back: ${money(after.chore_pay_pence)}, which was at risk.`,
    )
  } else if (effect.loses_the_chore_pay) {
    lines.push(
      `The chore money is lost: ${money(before.chore_pay_pence)} the week was going to pay.`,
    )
  } else if (!after.chore_pay_awarded && after.chore_pay_at_stake_pence > 0) {
    lines.push(
      `The chore money stays at risk: ${money(
        after.chore_pay_at_stake_pence,
      )}, all or nothing.`,
    )
  }

  if (before.misses_outstanding !== after.misses_outstanding) {
    lines.push(
      `Outstanding misses go from ${misses(before.misses_outstanding)} to ${misses(
        after.misses_outstanding,
      )}.`,
    )
  } else if (after.misses_outstanding > 0) {
    lines.push(`${misses(after.misses_outstanding)} still outstanding.`)
  }

  const gained = newRecoveries(before, after)
  if (gained.length) lines.push(`${list(gained)} — worked unpaid.`)
  const lost = lostRecoveries(before, after)
  if (lost.length) lines.push(`${list(lost)}.`)

  if (effect.difference_pence === 0) {
    lines.push(`The week stays at ${money(after.total_pence)}.`)
  } else {
    const direction = effect.difference_pence > 0 ? 'up' : 'down'
    lines.push(
      `The week goes from ${money(before.total_pence)} to ${money(
        after.total_pence,
      )} — ${direction} ${money(Math.abs(effect.difference_pence))}.`,
    )
  }

  return lines
}

/** The one line that goes on the button, and into the PIN dialog. */
export function consequenceSummary(effects: Consequence[]): string {
  if (effects.length === 0) return 'This changes nothing.'
  if (effects.length === 1) {
    const effect = effects[0]
    return `${weekLabel(effect.start_date, effect.end_date)}: ${money(
      effect.before.total_pence,
    )} → ${money(effect.after.total_pence)}`
  }
  return `${effects.length} weeks, ${money(
    effects.reduce((sum, effect) => sum + effect.difference_pence, 0),
  )} in total`
}

/** How a queue item names itself: the chore, and which occasion of it. */
export function pendingLabel(claim: Pending): string {
  if (claim.due_date) {
    return `${claim.name} — ${shortDate(claim.due_date)}`
  }
  if (claim.sequence > 1) return `${claim.name} — ${claim.sequence}${ordinal(claim.sequence)} time`
  return claim.name
}

function ordinal(sequence: number): string {
  return sequence === 1 ? 'st' : sequence === 2 ? 'nd' : sequence === 3 ? 'rd' : 'th'
}

/** "Monday", capitalised — the tokens themselves are lowercase, like the enums. */
export function weekdayLabel(day: Weekday): string {
  return day.charAt(0).toUpperCase() + day.slice(1)
}

/** "Tuesday", "Tuesday and Friday", "Monday, Wednesday and Saturday". */
function weekdaysList(weekdays: Weekday[]): string {
  return list(weekdays.map(weekdayLabel))
}

/** How a chore's cadence reads on the management screen, its own shape included. */
export function cadenceLabel(
  cadence: Cadence,
  timesPerWeek: number | null,
  weekdays: Weekday[] | null = null,
): string {
  switch (cadence) {
    case 'daily':
      return 'Every day'
    case 'weekdays':
      return weekdays && weekdays.length > 0 ? weekdaysList(weekdays) : 'Chosen days'
    case 'weekly_count':
      return timesPerWeek === 1
        ? 'Once a week'
        : `${timesPerWeek ?? '?'} times a week`
    case 'weekly_condition':
      return 'All week, judged on Sunday'
    case 'one_off':
      return 'One-off'
    case 'event':
      return 'Logged by a parent when it happens'
    default:
      return cadence
  }
}

/** How long a claim has been waiting, for a queue that is worked on Sundays. */
export function waitingFor(claimedAt: string | null): string {
  if (!claimedAt) return ''
  const hours = Math.floor((Date.now() - new Date(claimedAt).getTime()) / 3_600_000)
  if (hours < 1) return 'just now'
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days} ${plural(days, 'day', 'days')} ago`
}
