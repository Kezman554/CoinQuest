/**
 * Three screens on one wall.
 *
 * The child's week is what the app opens on, every time. Savings and Parent
 * are both reached by deliberately quiet controls at the foot of the page and
 * neither is what a fresh load lands on: the screen lives in a kitchen and is
 * read a dozen times a day by someone who came to see the week, not to
 * navigate a dashboard.
 *
 * The two are not the same kind of quiet, though. Savings is read-only and
 * needs no credential — offering it costs nothing, and it is where "how much
 * have I got" actually lives now that this feature exists. Parent asks for a
 * PIN the moment anything on it tries to move money.
 *
 * The switch is presentation and nothing else. It hides no authorisation —
 * every act on the parent side carries a PIN the server checks, and a person
 * who taps their way here without one can read what is already readable and do
 * nothing at all. Hiding a button is not a security control, and this one is
 * not pretending to be.
 */

import { useCallback, useEffect, useState } from 'react'
import './App.css'
import { claim, clearMiss, loadWeek, loadWeekById, loadWeeks, markMissed } from './api'
import type { InstanceCard, WeekSummary, WeekView } from './api'
import { Days } from './components/Days'
import type { PinAct } from './components/parent/PinDialog'
import { PinDialog } from './components/parent/PinDialog'
import { Recovery } from './components/Recovery'
import { Total } from './components/Total'
import { Weekly } from './components/Weekly'
import { NotCurrentBanner, WeekNav } from './components/WeekNav'
import { ParentView } from './ParentView'
import { SavingsView } from './SavingsView'
import { longDate, shortDate, weekdayOf } from './words'

type Screen = 'child' | 'savings' | 'parent'

function App() {
  const [screen, setScreen] = useState<Screen>('child')

  return (
    <main className="page">
      {screen === 'child' && <ChildWeek />}
      {screen === 'savings' && <SavingsView />}
      {screen === 'parent' && <Parent />}

      <footer className="switcher">
        {screen === 'child' ? (
          <>
            <button type="button" className="button button-quiet" onClick={() => setScreen('savings')}>
              Savings
            </button>
            <button type="button" className="button button-quiet" onClick={() => setScreen('parent')}>
              Parent
            </button>
          </>
        ) : (
          <button type="button" className="button button-quiet" onClick={() => setScreen('child')}>
            Back to the week
          </button>
        )}
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
 * One screen, read standing up from a distance, with three things to do on
 * it: say a chore is done, say one was missed, and — with the PIN — take that
 * back. Everything else is there to be read rather than operated.
 *
 * The page reloads its whole state after every one of them rather than
 * patching the row in place. That is what makes the figure honest: marking a
 * miss removes the whole chore pot and changes the recovery notice and the
 * make-good line as well as the tile that was tapped, and the new figure is
 * re-read from the engine's own proposal rather than worked out here. A view
 * that subtracted £2 itself would be a second implementation of the
 * all-or-nothing rule, the cap and the optimiser, and it would eventually
 * disagree with what actually settles.
 */
function ChildWeek() {
  const [week, setWeek] = useState<WeekView | null>(null)
  const [weeks, setWeeks] = useState<WeekSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  //: The one act on this screen that asks for the PIN. The dialog is the
  //: parent view's own, unchanged: it states the consequence, holds the PIN
  //: for the length of the call, and unmounts with it.
  const [act, setAct] = useState<PinAct | null>(null)

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

  const viewed = week && !week.is_current ? week.week_id : null

  const onClaim = useCallback(
    async (instanceId: number) => {
      setBusyId(instanceId)
      try {
        await claim(instanceId)
        await refresh(viewed)
      } catch (problem) {
        setError((problem as Error).message)
      } finally {
        setBusyId(null)
      }
    },
    [refresh, viewed],
  )

  /** No PIN, and no confirmation step either. The requirement is the ten
   *  seconds a parent has while noticing it; a dialog in the middle of that
   *  is the same defeat the PIN was. The undo is the safety net, and it is
   *  right there on the tile. */
  const onMissed = useCallback(
    async (instanceId: number) => {
      setBusyId(instanceId)
      try {
        await markMissed(instanceId)
        await refresh(viewed)
      } catch (problem) {
        setError((problem as Error).message)
      } finally {
        setBusyId(null)
      }
    },
    [refresh, viewed],
  )

  const onClearMiss = useCallback((chore: InstanceCard) => {
    setAct({
      title: 'Not missed after all',
      summary: `${chore.name}${
        chore.due_date ? ` on ${longDate(chore.due_date)}` : ''
      } goes back to not yet done.`,
      lines: [
        'It becomes claimable again, and the chore money it was holding up comes back to the week.',
      ],
      confirmLabel: 'Clear the miss',
      run: (pin) => clearMiss(pin, chore.instance_id as number),
    })
  }, [])

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

  // The missed control follows the same rule the claim button does: it exists
  // on the week that is actually now, and nowhere else. A week paged back to
  // is history being read, and history is not ruled on from this screen.
  const rulable = week.is_current && week.status === 'open'

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
      <Total
        totals={shown.totals}
        status={shown.status}
        makeGood={shown.recovery.make_good}
      />
      <Days
        days={shown.days}
        onClaim={onClaim}
        busyId={busyId}
        onMissed={rulable ? onMissed : undefined}
        onClearMiss={rulable ? onClearMiss : undefined}
      />
      <Weekly
        weekly={shown.weekly}
        onClaim={onClaim}
        busyId={busyId}
        deadlineWeekday={weekdayOf(shown.end_date)}
      />

      {act && (
        <PinDialog
          act={act}
          onClose={() => setAct(null)}
          onDone={() => {
            setAct(null)
            void refresh(viewed)
          }}
        />
      )}
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
