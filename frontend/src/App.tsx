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

import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { claim, loadWeek } from './api'
import type { WeekView } from './api'
import { Days } from './components/Days'
import { Recovery } from './components/Recovery'
import { Total } from './components/Total'
import { Weekly } from './components/Weekly'
import { shortDate, weekdayOf } from './words'

function App() {
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
      <main className="page">
        <p className="problem" role="alert">
          Cannot reach CoinQuest: {error}
        </p>
      </main>
    )
  }

  if (!week) {
    return (
      <main className="page">
        <p className="loading">Loading your week…</p>
      </main>
    )
  }

  return (
    <main className="page">
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
    </main>
  )
}

export default App
