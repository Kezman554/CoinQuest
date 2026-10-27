/**
 * The parent's screen.
 *
 * One rule runs through all of it: the PIN is asked for per submission, by a
 * dialog that states what is about to happen, and is kept nowhere afterwards.
 * There is no unlocked mode. Every act goes through `ask`, which mounts the
 * dialog; the dialog is unmounted the moment the act finishes, taking the
 * value with it.
 *
 * After anything succeeds the whole screen reloads its data rather than
 * patching a row. Confirming a claim moves the queue, the week's figures, what
 * is owed and possibly the savings balance, and a screen showing one of those
 * fresh beside three that are stale is worse than one that waits half a
 * second.
 *
 * It is split into three tabs because one page of every section had become a
 * long scroll: the weekly money work, managing chores, and savings. The tab
 * lives in state here, and a refresh replaces the data without remounting
 * this component, so finishing an act leaves the parent on the tab they were
 * using. A tab carries a count when something on it is waiting for a parent,
 * since a queue on a tab nobody is looking at is otherwise easy to miss.
 */

import { useCallback, useEffect, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { DueMonth, WeekView } from './api'
import type {
  ChoreDefinition,
  Consequence,
  DecisionIn,
  DepositRequest,
  Depositors,
  Owed,
  Pending,
  Preset,
  SavingsMatchProposal,
  SchemeSettings,
  Savings,
  SettledMonth,
  WeekSummary,
} from './parentApi'
import {
  loadChores,
  loadCurrentWeek,
  loadDepositors,
  loadOwed,
  loadPendingDeposits,
  loadPresets,
  loadQueue,
  loadSavings,
  loadSavingsMatchProposal,
  loadSchemeSettings,
  loadSettledMonths,
  loadDueMonths,
  loadWeeks,
  loadWeekView,
  submitReview,
} from './parentApi'
import { Chores } from './components/parent/Chores'
import { ClosedWeeks } from './components/parent/ClosedWeeks'
import { Payday, Rewards, SavingsPanel } from './components/parent/Money'
import type { PinAct } from './components/parent/PinDialog'
import { PinDialog } from './components/parent/PinDialog'
import { Queue } from './components/parent/Queue'
import { SavingsMatch } from './components/parent/SavingsMatch'
import { ThisWeek } from './components/parent/ThisWeek'
import { WeekBrowser } from './components/parent/WeekBrowser'
import { batchAction, batchDone, consequenceLines, consequenceSummary } from './parentWords'

type Everything = {
  queue: Pending[]
  week: WeekView | null
  weeks: WeekSummary[]
  owed: Owed[]
  savings: Savings
  presets: Preset[]
  chores: ChoreDefinition[]
  schemeSettings: SchemeSettings
  settledMonths: SettledMonth[]
  //: Ended months the match has not been settled for, oldest first.
  dueMonths: DueMonth[]
  //: Null when there is nothing yet to project — the savings ledger has no
  //: entries at all. Not the same as an error: the panel reads it as "no
  //: match to show yet", the way an unopened week reads as "nothing owed".
  savingsMatchProposal: SavingsMatchProposal | null
  savingsMatchProposalError: string | null
  //: Who a deposit's "posted by" may name — config, not schema. Null only
  //: while still loading, same as everything else in this type.
  depositors: Depositors | null
  pendingDeposits: DepositRequest[]
  //: Weeks that are open but are not the calendar's current one — in
  //: practice, a week that has been reopened and is waiting to be settled
  //: again. More than one can exist: reopening is eligible on "the most
  //: recent closed week", and reopening one can make an earlier one
  //: eligible too, so a parent may work back through several before
  //: resettling any of them.
  reopenedWeeks: WeekView[]
}

type Tab = 'week' | 'chores' | 'savings'

const TABS: { id: Tab; label: string }[] = [
  { id: 'week', label: 'This week' },
  { id: 'chores', label: 'Chores' },
  { id: 'savings', label: 'Savings' },
]

export function ParentView() {
  const [tab, setTab] = useState<Tab>('week')
  const [data, setData] = useState<Everything | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [act, setAct] = useState<PinAct | null>(null)
  //: Who the last batch was agreed by — the PIN's parent, by name.
  const [lastBatch, setLastBatch] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [
        queue,
        weeks,
        owed,
        savings,
        presets,
        chores,
        schemeSettings,
        settledMonths,
        dueMonths,
        depositors,
        pendingDeposits,
      ] = await Promise.all([
        loadQueue(),
        loadWeeks(),
        loadOwed(),
        loadSavings(),
        loadPresets(),
        loadChores(),
        loadSchemeSettings(),
        loadSettledMonths(),
        loadDueMonths(),
        loadDepositors(),
        loadPendingDeposits(),
      ])
      // The current week may not be open, or may not exist yet. Neither is an
      // error, and neither should empty the rest of the screen.
      const week = await loadCurrentWeek().catch(() => null)

      // No proposal to show is a real state too — the savings ledger has no
      // entries yet — not a reason to empty the rest of the screen either.
      let savingsMatchProposal = null
      let savingsMatchProposalError: string | null = null
      try {
        savingsMatchProposal = await loadSavingsMatchProposal()
      } catch (problem) {
        savingsMatchProposalError = (problem as Error).message
      }

      // Any other open week is one a reopen put back there, waiting to be
      // settled again.
      const reopenedIds = weeks
        .filter((w) => w.status === 'open' && w.week_id !== week?.week_id)
        .map((w) => w.week_id)
      const reopenedWeeks = await Promise.all(reopenedIds.map(loadWeekView))

      setData({
        queue,
        week,
        weeks,
        owed,
        savings,
        presets,
        chores,
        schemeSettings,
        settledMonths,
        dueMonths,
        savingsMatchProposal,
        savingsMatchProposalError,
        reopenedWeeks,
        depositors,
        pendingDeposits,
      })
      setError(null)
    } catch (problem) {
      setError((problem as Error).message)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const ask = useCallback((next: PinAct) => setAct(next), [])

  const submitBatch = useCallback(
    (decisions: DecisionIn[], effects: Consequence[]) => {
      const confirmed = decisions.filter((d) => d.decision === 'confirm').length
      ask({
        title: batchAction(confirmed, decisions.length - confirmed),
        summary: consequenceSummary(effects),
        lines: effects.flatMap((effect) => consequenceLines(effect)),
        confirmLabel: 'Confirm the batch',
        run: (pin) =>
          submitReview(pin, decisions).then((result) => {
            setLastBatch(batchDone(result.confirmed.length, result.rejected.length, result.authorised_by))
          }),
      })
    },
    [ask],
  )

  if (error && !data) {
    return (
      <p className="problem" role="alert">
        Cannot reach CoinQuest: {error}
      </p>
    )
  }

  if (!data) return <p className="loading">Loading…</p>

  return (
    <>
      {error && (
        <p className="problem" role="alert">
          {error}
        </p>
      )}

      <Tabs
        current={tab}
        onChoose={setTab}
        waiting={{
          week: data.queue.length,
          chores: 0,
          savings: data.pendingDeposits.length,
        }}
      />

      <div role="tabpanel" id={`parent-panel-${tab}`} aria-labelledby={`parent-tab-${tab}`}>
        {tab === 'week' && (
          <>
            {lastBatch && (
              <p className="act-note last-batch" role="status">
                {lastBatch}
              </p>
            )}
            <Queue queue={data.queue} onSubmit={submitBatch} />

            <WeekBrowser
              currentWeek={data.week}
              weeks={data.weeks}
              ask={ask}
              onDone={() => void refresh()}
            />

            {data.reopenedWeeks.map((week) => (
              <ThisWeek
                key={week.week_id}
                week={week}
                ask={ask}
                onDone={() => void refresh()}
                title="Reopened week"
              />
            ))}

            <Payday owed={data.owed} ask={ask} />
            <ClosedWeeks weeks={data.weeks} ask={ask} />
          </>
        )}

        {tab === 'chores' && (
          <>
            <Chores chores={data.chores} schemeSettings={data.schemeSettings} ask={ask} />
            <Rewards presets={data.presets} ask={ask} />
          </>
        )}

        {tab === 'savings' && (
          <>
            <SavingsPanel
              savings={data.savings}
              depositors={data.depositors}
              pendingDeposits={data.pendingDeposits}
              ask={ask}
            />
            <SavingsMatch
              proposal={data.savingsMatchProposal}
              proposalError={data.savingsMatchProposalError}
              settledMonths={data.settledMonths}
              dueMonths={data.dueMonths}
              ask={ask}
            />
          </>
        )}
      </div>

      <p className="pin-note">
        The PIN is asked for once per submission and is never kept. Every one of
        these is refused by the server without it, whatever this screen shows.
      </p>

      {act && (
        <PinDialog
          act={act}
          onClose={() => setAct(null)}
          onDone={() => {
            setAct(null)
            void refresh()
          }}
        />
      )}
    </>
  )
}

/**
 * The three tabs. Plain buttons with the tab roles on them, so a screen
 * reader hears a tab list, and the arrow keys move along it as they would in
 * any other. Presentation only: what a tab hides is still readable by anyone
 * and still refused by the server without the PIN.
 */
function Tabs({
  current,
  onChoose,
  waiting,
}: {
  current: Tab
  onChoose: (tab: Tab) => void
  waiting: Record<Tab, number>
}) {
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (step === 0) return
    const at = TABS.findIndex((t) => t.id === current)
    const next = TABS[(at + step + TABS.length) % TABS.length].id
    onChoose(next)
    document.getElementById(`parent-tab-${next}`)?.focus()
  }

  return (
    <div className="parent-tabs" role="tablist" aria-label="Parent sections" onKeyDown={move}>
      {TABS.map(({ id, label }) => {
        const chosen = id === current
        return (
          <button
            key={id}
            id={`parent-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={chosen}
            aria-controls={`parent-panel-${id}`}
            tabIndex={chosen ? 0 : -1}
            className={chosen ? 'parent-tab chosen' : 'parent-tab'}
            onClick={() => onChoose(id)}
          >
            {label}
            {waiting[id] > 0 && (
              <span className="parent-tab-count" aria-label={`${waiting[id]} waiting`}>
                {waiting[id]}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}
