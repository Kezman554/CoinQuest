/**
 * The wording, in one place.
 *
 * This screen is read by a nine-year-old, standing up, from across a kitchen.
 * That rules out most of what a dashboard would normally say. No jargon from
 * the scheme reaches the child: "instance", "settlement", "assignment" and
 * "cadence" are words about the books, not about his week.
 *
 * Two rules the phrasing keeps to:
 *
 *  - Nothing is described as lost while he can still do something about it.
 *    An untouched chore on a day already gone is "not yet", never "missed",
 *    because it is still claimable right up until the week settles.
 *  - A count of one never reads as "1 times". These are read aloud.
 */

import type { InstanceCard, MakeGood, RecoveryPanel, WeeklyCard } from './api'
import { money } from './api'

export function plural(count: number, one: string, many: string): string {
  return count === 1 ? one : many
}

/** "the bed", "the bed and the cat", "the bed, the cat and the path".
 *
 * The conjunction is a parameter because the two lists on this screen mean
 * opposite things: the misses are all of them, and the bonus chores that would
 * cover one are any one of them. */
export function list(items: string[], conjunction = 'and'): string {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} ${conjunction} ${
    items[items.length - 1]
  }`
}

/** "1 day", "3 days", and "today" rather than "0 days". */
export function daysLeft(days: number): string {
  if (days <= 0) return 'today'
  if (days === 1) return '1 more day'
  return `${days} more days`
}

/** What the button on a chore says, or what stands in its place. */
export function stateLabel(chore: InstanceCard): string {
  switch (chore.state) {
    case 'confirmed':
      return 'Done'
    case 'claimed':
      return 'Waiting to be checked'
    case 'missed':
      return 'Missed'
    default:
      return chore.rejection_count > 0 ? 'Have another go' : "I've done it"
  }
}

/**
 * Why a chore that looks untouched is not untouched.
 *
 * A rejected claim goes back to untouched, which is the right state and an
 * unreadable one: without this line a refusal looks exactly like a tap that
 * never registered, and he taps it again into the same refusal.
 */
export function rejectionNote(chore: InstanceCard): string | null {
  if (chore.rejection_count === 0) return null
  if (chore.rejection_count === 1) return 'Not accepted last time'
  return `Not accepted ${chore.rejection_count} times`
}

/** "1st time", "2nd time", for one occasion of a chore wanted several. */
export function occasion(sequence: number): string {
  const suffix =
    sequence === 1 ? 'st' : sequence === 2 ? 'nd' : sequence === 3 ? 'rd' : 'th'
  return `${sequence}${suffix} time`
}

/** "2 of 3 done", for a chore the week wants a number of times. */
export function progress(card: WeeklyCard): string {
  return `${card.confirmed} of ${card.required} done`
}

export type Notice = {
  tone: 'urgent' | 'todo' | 'sorted'
  headline: string
  detail: string
}

/**
 * What the recovery panel says, which changes with how much time is left.
 *
 * The three wordings are three different situations and not three volumes of
 * the same one. "You have until Saturday" is advice while there is a tomorrow
 * to act in; inside the last day it is no longer advice, so the wording says
 * what is actually true instead — today or not at all.
 */
export function recoveryNotice(
  recovery: RecoveryPanel,
  weekdayOfDeadline: string,
): Notice | null {
  if (recovery.outstanding === 0) {
    if (recovery.covered === 0) return null
    const covered = recovery.needs
      .filter((need) => need.covered_by)
      .map((need) => `${need.miss_name} — you did ${need.covered_by} instead`)
    return {
      tone: 'sorted',
      headline: plural(recovery.covered, 'Put right', 'All put right'),
      detail: `${covered.join('. ')}.`,
    }
  }

  const outstanding = recovery.needs.filter((need) => !need.covered_by)
  const missed = list(outstanding.map((need) => need.miss_name))
  // `options` is one entry per claimable occasion, not one per chore — a
  // bonus chore wanted more than once a week can still have two occasions
  // open at once, and both name the same chore. Naming it twice reads as two
  // choices ("do X or X") when it is one, so the sentence is built from the
  // distinct names, in the order they first appear.
  const options = [...new Set(recovery.options.map((option) => option.name))]
  const them = plural(outstanding.length, 'it', 'them')

  // Nothing left to do it with. Saying how long is left would be pointing at
  // a clock for a race that is already over.
  if (options.length === 0) {
    return {
      tone: recovery.urgent ? 'urgent' : 'todo',
      headline: `You missed ${missed}`,
      detail: `There is no bonus chore left this week to put ${them} right.`,
    }
  }

  const how = `Do ${list(options, 'or')} to put ${them} right.`

  if (recovery.urgent) {
    return {
      tone: 'urgent',
      headline: `Today is the last day to fix ${missed}`,
      detail: `${how} The week ends tonight.`,
    }
  }

  // More misses than the week allows recoveries for: saying "do a bonus
  // chore" would be promising something the rules cannot deliver.
  const capped =
    outstanding.length > recovery.cap
      ? ` Only ${recovery.cap} can be put right in one week.`
      : ''

  return {
    tone: 'todo',
    headline: `You missed ${missed}`,
    detail: `${how}${capped} You have ${daysLeft(
      recovery.days_remaining,
    )} — until ${weekdayOfDeadline}.`,
  }
}

/**
 * The one line beside the figure: what to do, and what it takes the week to.
 *
 * Both halves are the engine's, not this file's — see MakeGood. It is one
 * sentence rather than a panel because it belongs beside the number it
 * restores, and because the person most likely to read it is somebody who has
 * just walked past the wall and marked nothing at all.
 *
 * Null when there is no route back, which renders as nothing. "You can still
 * fix this!" over a week that cannot be fixed is worse than silence.
 */
export function makeGoodLine(makeGood: MakeGood | null): string | null {
  if (!makeGood || makeGood.names.length === 0) return null
  // "and", not "or": where the route needs two chores it needs both of them.
  return `Do ${list(makeGood.names)} to put it right — that takes this week back to ${money(
    makeGood.restores_to_pence,
  )}.`
}

/** "Sunday 16 August", for a heading that has to be read from a distance. */
export function longDate(iso: string): string {
  const date = new Date(`${iso}T12:00:00`)
  return date.toLocaleDateString('en-GB', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

export function shortDate(iso: string): string {
  const date = new Date(`${iso}T12:00:00`)
  return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'long' })
}

/** "September 2026", for a month named rather than dated — the savings
 * match settles by the calendar month, not by a week's own dates. */
export function monthName(iso: string): string {
  const date = new Date(`${iso}T12:00:00`)
  return date.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })
}

export function weekdayOf(iso: string): string {
  const date = new Date(`${iso}T12:00:00`)
  return date.toLocaleDateString('en-GB', { weekday: 'long' })
}
