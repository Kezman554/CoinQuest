/**
 * Paging back through weeks, and a way back to now.
 *
 * A week only exists as a row once it has been opened, so "previous" means
 * the nearest earlier row that actually exists, not a calendar date nobody
 * has touched. The banner is the loud half of this: a wall screen left open
 * on last week has to say so at a glance, not in a date nobody reads closely
 * standing across a kitchen.
 */

import type { ReactNode } from 'react'

import type { WeekStatus, WeekSummary } from '../api'
import { shortDate } from '../words'

type NavProps = {
  weeks: WeekSummary[]
  viewedWeekId: number
  onNavigate: (weekId: number) => void
}

export function WeekNav({ weeks, viewedWeekId, onNavigate }: NavProps) {
  const ordered = [...weeks].sort((a, b) => a.start_date.localeCompare(b.start_date))
  const index = ordered.findIndex((week) => week.week_id === viewedWeekId)
  const previous = index > 0 ? ordered[index - 1] : null
  const next = index >= 0 && index < ordered.length - 1 ? ordered[index + 1] : null

  return (
    <nav className="week-nav" aria-label="Browse other weeks">
      <button
        type="button"
        className="button week-nav-button"
        disabled={!previous}
        onClick={() => previous && onNavigate(previous.week_id)}
      >
        ← {previous ? shortDate(previous.start_date) : 'No earlier week'}
      </button>
      <button
        type="button"
        className="button week-nav-button"
        disabled={!next}
        onClick={() => next && onNavigate(next.week_id)}
      >
        {next ? shortDate(next.start_date) : 'This is the latest'} →
      </button>
    </nav>
  )
}

/**
 * The banner over a week that is not this one, which says two different
 * things depending on whether that week has been agreed.
 *
 * An open week paged back to is not history yet. Anything done on one of
 * its days and ticked by nobody can still be ticked, and this has to be said
 * out loud, because the tiles below it used to be locked and a person who
 * remembers that will not try. It also has to say what a late tick means: it
 * says the chore was done on that day. The make-good window closed with the
 * week, and doing a bonus chore now does not reopen it — see
 * app/routers/claims.py.
 *
 * A settled or voided week is closed forever, and reads as it always did.
 *
 * The parent screen shows the same banner over the same open week, with
 * settlement controls under it rather than tiles, so it passes its own
 * `openNote`; the default is the child's.
 */
export function NotCurrentBanner({
  startDate,
  endDate,
  status,
  onBackToNow,
  openNote,
}: {
  startDate: string
  endDate: string
  status: WeekStatus
  onBackToNow: () => void
  openNote?: ReactNode
}) {
  return (
    <section className="notice notice-away" role="status">
      <h2>
        Not the current week — {shortDate(startDate)} to {shortDate(endDate)}
      </h2>
      {status === 'open' ? (
        <p>
          {openNote ?? (
            <>
              This week is still waiting to be agreed. If you did a chore on
              one of these days and forgot to tick it, you can still tick it
              now. Ticking says you did it on that day — a chore done this
              week counts for this week, not for last.
            </>
          )}
        </p>
      ) : (
        <p>You are looking back through history. Nothing here can be changed.</p>
      )}
      <button type="button" className="button button-do" onClick={onBackToNow}>
        Back to this week
      </button>
    </section>
  )
}
