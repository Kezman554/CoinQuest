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
import { claim, loadWeek } from './api'
import type { WeekView } from './api'
import { Days } from './components/Days'
import { Recovery } from './components/Recovery'
import { Total } from './components/Total'
import { Weekly } from './components/Weekly'
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
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const refresh = useCallback(async () => {
    try {
      setWeek(await loadWeek())
      setError(null)
    } catch (problem) {
      setError((problem as Error).message)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const onClaim = useCallback(
    async (instanceId: number) => {
      setBusyId(instanceId)
      try {
        await claim(instanceId)
        await refresh()
      } catch (problem) {
        setError((problem as Error).message)
      } finally {
        setBusyId(null)
      }
    },
    [refresh],
  )

  if (error && !week) {
    return (
      <p className="problem" role="alert">
        Cannot reach CoinQuest: {error}
      </p>
    )
  }

  if (!week) return <p className="loading">Loading your week…</p>

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

      <Recovery recovery={week.recovery} />
      <Total totals={week.totals} />
      <Days days={week.days} onClaim={onClaim} busyId={busyId} />
      <Weekly
        weekly={week.weekly}
        onClaim={onClaim}
        busyId={busyId}
        deadlineWeekday={weekdayOf(week.end_date)}
      />
    </>
  )
}

export default App
