/**
 * Four screens on one wall.
 *
 * The child's week is what the app opens on, every time. Savings, Lifetime
 * and Parent are all reached by deliberately quiet controls at the foot of
 * the page and none is what a fresh load lands on: the screen lives in a
 * kitchen and is read a dozen times a day by someone who came to see the
 * week, not to navigate a dashboard.
 *
 * Parent is not the same kind of quiet as the other two. Savings and
 * Lifetime are read-only and need no credential — offering them costs
 * nothing, and between them they are where "how much have I got" and "what
 * has this ever come to" actually live now that both features exist. Parent
 * asks for a PIN the moment anything on it tries to move money.
 *
 * The switch is presentation and nothing else. It hides no authorisation —
 * every act on the parent side carries a PIN the server checks, and a person
 * who taps their way here without one can read what is already readable and do
 * nothing at all. Hiding a button is not a security control, and this one is
 * not pretending to be.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import './App.css'
import { claim, clearMiss, loadWeek, loadWeekById, loadWeeks } from './api'
import type { InstanceCard, WeekSummary, WeekView } from './api'
import { Days } from './components/Days'
import { Owed } from './components/Owed'
import type { PinAct } from './components/parent/PinDialog'
import { PinDialog } from './components/parent/PinDialog'
import { Bricks } from './components/Bricks'
import { Total } from './components/Total'
import { Weekly } from './components/Weekly'
import { NotCurrentBanner, WeekNav } from './components/WeekNav'
import { LifetimeView } from './LifetimeView'
import { ParentView } from './ParentView'
import { loadOwed } from './parentApi'
import type { Owed as OwedWeek } from './parentApi'
import { SavingsView } from './SavingsView'
import { longDate, shortDate, weekdayOf } from './words'

type Screen = 'child' | 'savings' | 'lifetime' | 'parent'

function App() {
  const [screen, setScreen] = useState<Screen>('child')

  // On the week they sit in its title row rather than a footer: the wall
  // panel is 800px tall, and a row of its own was height the days needed.
  const elsewhere = (
    <nav className="switcher" aria-label="Other screens">
      <button type="button" className="button button-quiet" onClick={() => setScreen('savings')}>
        Savings
      </button>
      <button type="button" className="button button-quiet" onClick={() => setScreen('lifetime')}>
        Lifetime
      </button>
      <button type="button" className="button button-quiet" onClick={() => setScreen('parent')}>
        Parent
      </button>
    </nav>
  )

  return (
    <main className={screen === 'child' ? 'page page-wall' : 'page'}>
      {screen === 'child' && (
        <>
          <Bricks />
          <ChildWeek elsewhere={elsewhere} />
        </>
      )}
      {screen === 'savings' && <SavingsView />}
      {screen === 'lifetime' && <LifetimeView />}
      {screen === 'parent' && <Parent onBack={() => setScreen('child')} />}

      {screen !== 'child' && (
        <footer className="switcher">
          <button type="button" className="button button-quiet" onClick={() => setScreen('child')}>
            Back to the week
          </button>
        </footer>
      )}
    </main>
  )
}

/**
 * The parent screen carries more than a screenful even split into tabs —
 * the weekly work alone holds the queue, the open weeks, what is owed and
 * the closed weeks — so the way back is offered at the top as well as the
 * bottom. The footer control is
 * still there for whoever has scrolled to it; this one is for whoever
 * hasn't.
 */
function Parent({ onBack }: { onBack: () => void }) {
  return (
    <>
      <button type="button" className="button button-quiet button-back-top" onClick={onBack}>
        Back to the week
      </button>
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
 * One screen, read standing up from a distance, with two things to do on it:
 * say a chore is done, and — with the PIN — take back a miss a parent marked.
 * Marking the miss itself lives on the parent screen; on the tiles it was a
 * second button under every chore, a child's mis-tap away from the one he
 * meant. Everything else is there to be read rather than operated.
 *
 * Laid out for the kitchen's 1280x800 touch panel: what this week is heading
 * for and what earlier weeks are still owed share a strip above the days, so
 * the whole week fits without a page scroll; a wider screen stands them down
 * either side instead. See the wall section of App.css.
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
function ChildWeek({ elsewhere }: { elsewhere: ReactNode }) {
  const [week, setWeek] = useState<WeekView | null>(null)
  const [weeks, setWeeks] = useState<WeekSummary[]>([])
  const [owed, setOwed] = useState<OwedWeek[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  //: The one act on this screen that asks for the PIN. The dialog is the
  //: parent view's own, unchanged: it states the consequence, holds the PIN
  //: for the length of the call, and unmounts with it.
  const [act, setAct] = useState<PinAct | null>(null)
  const days = useRef<HTMLDivElement>(null)

  // `null` means "the current week" — the one the screen always opens on and
  // returns to. A specific id means paging back has landed on that week.
  const refresh = useCallback(async (viewedWeekId: number | null) => {
    try {
      // The current week always loads too, whichever is being shown: it is
      // what "back to this week" returns to, and its id is what tells a
      // shown week apart from being the current one.
      const [current, list, outstanding] = await Promise.all([
        loadWeek(),
        loadWeeks(),
        loadOwed(),
      ])
      setWeeks(list)
      setOwed(outstanding)
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

  // The scroll hint. Seven across, the days region scrolls on its own when a
  // heavy week outgrows it, and on a wall nobody sees a scrollbar — so while
  // there is more below, the region says so (data-more), and App.css fades
  // its bottom edge into the ground. Gone once the last row is in view.
  useEffect(() => {
    const region = days.current
    if (!region) return
    const update = () => {
      const more = region.scrollHeight - region.clientHeight - region.scrollTop > 1
      region.toggleAttribute('data-more', more)
    }
    update()
    region.addEventListener('scroll', update, { passive: true })
    const resized = new ResizeObserver(update)
    resized.observe(region)
    for (const child of region.children) resized.observe(child)
    return () => {
      region.removeEventListener('scroll', update)
      resized.disconnect()
    }
  }, [week])

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
      <>
        <p className="problem" role="alert">
          Cannot reach CoinQuest: {error}
        </p>
        {elsewhere}
      </>
    )
  }

  if (!week) return <p className="loading">Loading your week…</p>

  // What can be tapped is the server's `can_claim`, rendered as it came. It
  // is true on every untouched day of an open week — however long ago the
  // day was, and whether or not the week is the current one — and false on
  // every tile of a settled or voided week. This screen used to lock every
  // week paged back to on top of that, which left a chore done on Wednesday
  // and ticked by nobody with no way to be recorded once Sunday came: the
  // week had moved on, the view read it as history, and the only thing that
  // could reach it was waiving the day. The gate is the week's settlement
  // state, and the server already applies it; see app/routers/claims.py.
  const shown = week

  // The PIN-guarded clear follows the same rule the claim button does: it
  // exists on any week that has not settled, and nowhere else.
  const rulable = week.status === 'open'

  return (
    <>
      <div className="wall-head">
        <header className="masthead">
          <h1>{week.child_name}&rsquo;s week</h1>
          <p className="dates">
            {shortDate(week.start_date)} &ndash; {shortDate(week.end_date)}
          </p>
        </header>
        <div className="wall-head-controls">
          <WeekNav weeks={weeks} viewedWeekId={week.week_id} onNavigate={onNavigate} />
          {elsewhere}
        </div>
      </div>

      {error && (
        <p className="problem" role="alert">
          {error}
        </p>
      )}
      {!week.is_current && (
        <NotCurrentBanner
          startDate={week.start_date}
          endDate={week.end_date}
          status={week.status}
          onBackToNow={onBackToNow}
        />
      )}

      <div className="wall">
        <aside className="wall-side wall-side-start">
          <Total
            totals={shown.totals}
            status={shown.status}
            makeGood={shown.recovery.make_good}
            recovery={shown.recovery}
          />
        </aside>
        <div className="wall-main" ref={days}>
          <Days
            days={shown.days}
            onClaim={onClaim}
            busyId={busyId}
            onClearMiss={rulable ? onClearMiss : undefined}
          />
          <Weekly
            weekly={shown.weekly}
            onClaim={onClaim}
            busyId={busyId}
            deadlineWeekday={weekdayOf(shown.end_date)}
          />
        </div>
        <aside className="wall-side wall-side-end">
          <Owed owed={owed} />
        </aside>
      </div>

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


export default App
