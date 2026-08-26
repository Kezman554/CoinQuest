/**
 * Two screens on one wall.
 *
 * The child's week is what the app opens on, every time. The parent's view is
 * reached by a deliberately quiet control at the foot of the page and is never
 * what a fresh load lands on: the screen lives in a kitchen and is read a
 * dozen times a day by the person who does not need it.
 *
 * The switch is presentation and nothing else. It hides no authorisation —
 * every act on the parent side carries a PIN the server checks, and a person
 * who taps their way here without one can read what is already readable and do
 * nothing at all. Hiding a button is not a security control, and this one is
 * not pretending to be.
 */

import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { claim, loadWeek, loadWeekById, loadWeeks } from './api'
import type { InstanceCard, WeekSummary, WeekView } from './api'
import { Days } from './components/Days'
import { Recovery } from './components/Recovery'
import { Total } from './components/Total'
import { Weekly } from './components/Weekly'
import { NotCurrentBanner, WeekNav } from './components/WeekNav'
import { ParentView } from './ParentView'
import { shortDate, weekdayOf } from './words'

type Screen = 'child' | 'parent'

function App() {
  const [screen, setScreen] = useState<Screen>('child')

  return (
    <main className="page">
      {screen === 'child' ? <ChildWeek /> : <Parent />}

      <footer className="switcher">
        <button
          type="button"
          className="button button-quiet"
          onClick={() => setScreen(screen === 'child' ? 'parent' : 'child')}
        >
          {screen === 'child' ? 'Parent' : "Back to the week"}
        </button>
      </footer>
    </main>
  )
}

function Parent() {
  return (
    <>
      <header className="masthead">
        <h1>Parent</h1>
        <p className="dates">Everything here is authorised one submission at a time</p>
      </header>
      <ParentView />
    </>
  )
}

/**
 * The child's week.
 *
 * One screen, read standing up from a distance, with one thing to do on it:
 * say a chore is done. Everything else is there to be read rather than
 * operated. The page reloads its whole state after every claim rather than
 * patching the row in place — a claim can change the recovery notice and the
 * projected total as well as the button that was tapped, and a screen that
 * shows a stale figure next to a fresh one is worse than one that waits.
 */
function ChildWeek() {
  const [week, setWeek] = useState<WeekView | null>(null)
  const [weeks, setWeeks] = useState<WeekSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  // `null` means "the current week" — the one the screen always opens on and
  // returns to. A specific id means paging back has landed on that week.
  const refresh = useCallback(async (viewedWeekId: number | null) => {
    try {
      // The current week always loads too, whichever is being shown: it is
      // what "back to this week" returns to, and its id is what tells a
      // shown week apart from being the current one.
      const [current, list] = await Promise.all([loadWeek(), loadWeeks()])
      setWeeks(list)
      if (viewedWeekId === null || viewedWeekId === current.week_id) {
        setWeek(current)
      } else {
        setWeek(await loadWeekById(viewedWeekId))
      }
      setError(null)
    } catch (problem) {
      setError((problem as Error).message)
    }
  }, [])

  useEffect(() => {
    void refresh(null)
  }, [refresh])

  const onNavigate = useCallback((weekId: number) => void refresh(weekId), [refresh])
  const onBackToNow = useCallback(() => void refresh(null), [refresh])

  const onClaim = useCallback(
    async (instanceId: number) => {
      setBusyId(instanceId)
      try {
        await claim(instanceId)
        await refresh(week && !week.is_current ? week.week_id : null)
      } catch (problem) {
        setError((problem as Error).message)
      } finally {
        setBusyId(null)
      }
    },
    [refresh, week],
  )

  if (error && !week) {
    return (
      <p className="problem" role="alert">
        Cannot reach CoinQuest: {error}
      </p>
    )
  }

  if (!week) return <p className="loading">Loading your week…</p>

  // A week paged back to is read-only regardless of whether it happens to
  // still be open — nothing to claim, nothing to press. See can_claim's own
  // rule, which is about the week's own status, not about what a screen
  // browsing history should offer.
  const shown = week.is_current ? week : asReadOnly(week)

  return (
    <>
      <header className="masthead">
        <h1>{week.child_name}&rsquo;s week</h1>
        <p className="dates">
          {shortDate(week.start_date)} &ndash; {shortDate(week.end_date)}
        </p>
      </header>

      {error && (
        <p className="problem" role="alert">
          {error}
        </p>
      )}

      <WeekNav weeks={weeks} viewedWeekId={week.week_id} onNavigate={onNavigate} />
      {!week.is_current && (
        <NotCurrentBanner
          startDate={week.start_date}
          endDate={week.end_date}
          onBackToNow={onBackToNow}
        />
      )}

      <Recovery recovery={shown.recovery} />
      <Total totals={shown.totals} status={shown.status} />
      <Days days={shown.days} onClaim={onClaim} busyId={busyId} />
      <Weekly
        weekly={shown.weekly}
        onClaim={onClaim}
        busyId={busyId}
        deadlineWeekday={weekdayOf(shown.end_date)}
      />
    </>
  )
}

/** Nothing claimable, whatever the raw instance states say. A week that is
 * technically still open but is not the one being paged back to as "now"
 * must not offer a button on the child's screen — see item 8. */
function asReadOnly(view: WeekView): WeekView {
  const locked = (card: InstanceCard): InstanceCard => ({ ...card, can_claim: false })
  return {
    ...view,
    days: view.days.map((day) => ({ ...day, chores: day.chores.map(locked) })),
    weekly: view.weekly.map((card) => ({
      ...card,
      instances: card.instances.map(locked),
    })),
    recovery: { ...view.recovery, options: view.recovery.options.map(locked) },
  }
}

export default App
