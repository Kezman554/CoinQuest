/**
 * Paging back through weeks, and a way back to now.
 *
 * A week only exists as a row once it has been opened, so "previous" means
 * the nearest earlier row that actually exists, not a calendar date nobody
 * has touched. The banner is the loud half of this: a wall screen left open
 * on last week has to say so at a glance, not in a date nobody reads closely
 * standing across a kitchen.
 */

import type { WeekSummary } from '../api'
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

export function NotCurrentBanner({
  startDate,
  endDate,
  onBackToNow,
}: {
  startDate: string
  endDate: string
  onBackToNow: () => void
}) {
  return (
    <section className="notice notice-away" role="status">
      <h2>
        Not the current week — {shortDate(startDate)} to {shortDate(endDate)}
      </h2>
      <p>You are looking back through history. Nothing here can be changed.</p>
      <button type="button" className="button button-do" onClick={onBackToNow}>
        Back to this week
      </button>
    </section>
  )
}
