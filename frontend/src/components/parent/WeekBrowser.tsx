/**
 * The current week, and a way to page back through the ones before it.
 *
 * A week only exists as a row once it has been opened, so "previous" means
 * the nearest earlier row — never a calendar date nobody has touched.
 * Paging to an open week (reopened, or simply never settled) reuses the
 * exact "This week" panel with full controls; paging to a closed one reuses
 * the exact detail "Closed weeks" already shows on expanding one. Two
 * renderings this screen already trusts, not a third built to match them.
 */

import { useEffect, useState } from 'react'
import type { WeekView } from '../../api'
import type { WeekSummary } from '../../parentApi'
import { loadWeekView } from '../../parentApi'
import { weekLabel } from '../../parentWords'
import { NotCurrentBanner, WeekNav } from '../WeekNav'
import { ClosedWeek, mostRecentClosedWeek } from './ClosedWeeks'
import type { PinAct } from './PinDialog'
import { ThisWeek } from './ThisWeek'

type Props = {
  currentWeek: WeekView | null
  weeks: WeekSummary[]
  ask: (act: PinAct) => void
  /** Reload the screen after an act that opened no PIN dialog to close. */
  onDone: () => void
}

export function WeekBrowser({ currentWeek, weeks, ask, onDone }: Props) {
  const [viewedWeekId, setViewedWeekId] = useState<number | null>(null)
  const [viewedOpenWeek, setViewedOpenWeek] = useState<WeekView | null>(null)

  const viewedSummary = weeks.find((week) => week.week_id === viewedWeekId) ?? null
  const isCurrent = viewedWeekId === null

  useEffect(() => {
    if (viewedWeekId === null || viewedSummary?.status !== 'open') {
      setViewedOpenWeek(null)
      return
    }
    let cancelled = false
    void loadWeekView(viewedWeekId).then((week) => {
      if (!cancelled) setViewedOpenWeek(week)
    })
    return () => {
      cancelled = true
    }
  }, [viewedWeekId, viewedSummary?.status])

  if (weeks.length === 0) {
    return currentWeek ? (
      <ThisWeek week={currentWeek} ask={ask} onDone={onDone} />
    ) : (
      <EmptyThisWeek />
    )
  }

  return (
    <>
      <WeekNav
        weeks={weeks}
        viewedWeekId={viewedWeekId ?? currentWeek?.week_id ?? weeks[weeks.length - 1].week_id}
        onNavigate={setViewedWeekId}
      />

      {!isCurrent && viewedSummary && (
        <NotCurrentBanner
          startDate={viewedSummary.start_date}
          endDate={viewedSummary.end_date}
          onBackToNow={() => setViewedWeekId(null)}
        />
      )}

      {isCurrent ? (
        currentWeek ? (
          <ThisWeek week={currentWeek} ask={ask} onDone={onDone} />
        ) : (
          <EmptyThisWeek />
        )
      ) : viewedSummary?.status === 'open' ? (
        viewedOpenWeek ? (
          <ThisWeek
            week={viewedOpenWeek}
            ask={ask}
            onDone={onDone}
            title={weekLabel(viewedSummary.start_date, viewedSummary.end_date)}
          />
        ) : (
          <p className="loading">Reading it…</p>
        )
      ) : viewedSummary ? (
        <section className="panel">
          <h2>{weekLabel(viewedSummary.start_date, viewedSummary.end_date)}</h2>
          <ClosedWeek
            weekId={viewedSummary.week_id}
            canReopen={viewedSummary.week_id === mostRecentClosedWeek(weeks)?.week_id}
            ask={ask}
          />
        </section>
      ) : null}
    </>
  )
}

function EmptyThisWeek() {
  return (
    <section className="panel">
      <h2>This week</h2>
      <p className="nothing">
        This week is closed, or has not been opened yet. Opening it happens the
        first time the child&rsquo;s screen is loaded.
      </p>
    </section>
  )
}
