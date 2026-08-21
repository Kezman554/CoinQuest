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
 */

import { useCallback, useEffect, useState } from 'react'
import type { WeekView } from './api'
import type {
  ChoreDefinition,
  Consequence,
  DecisionIn,
  Owed,
  Pending,
  Preset,
  SchemeSettings,
  Savings,
  WeekSummary,
} from './parentApi'
import {
  loadChores,
  loadCurrentWeek,
  loadOwed,
  loadPresets,
  loadQueue,
  loadSavings,
  loadSchemeSettings,
  loadWeeks,
  submitReview,
} from './parentApi'
import { Chores } from './components/parent/Chores'
import { ClosedWeeks } from './components/parent/ClosedWeeks'
import { Payday, Rewards, SavingsPanel } from './components/parent/Money'
import type { PinAct } from './components/parent/PinDialog'
import { PinDialog } from './components/parent/PinDialog'
import { Queue } from './components/parent/Queue'
import { ThisWeek } from './components/parent/ThisWeek'
import { batchAction, consequenceLines, consequenceSummary } from './parentWords'

type Everything = {
  queue: Pending[]
  week: WeekView | null
  weeks: WeekSummary[]
  owed: Owed[]
  savings: Savings
  presets: Preset[]
  chores: ChoreDefinition[]
  schemeSettings: SchemeSettings
}

export function ParentView() {
  const [data, setData] = useState<Everything | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [act, setAct] = useState<PinAct | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [queue, weeks, owed, savings, presets, chores, schemeSettings] = await Promise.all([
        loadQueue(),
        loadWeeks(),
        loadOwed(),
        loadSavings(),
        loadPresets(),
        loadChores(),
        loadSchemeSettings(),
      ])
      // The current week may not be open, or may not exist yet. Neither is an
      // error, and neither should empty the rest of the screen.
      const week = await loadCurrentWeek().catch(() => null)
      setData({ queue, week, weeks, owed, savings, presets, chores, schemeSettings })
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
        run: (pin) => submitReview(pin, decisions).then(() => undefined),
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

      <Queue queue={data.queue} onSubmit={submitBatch} />

      {data.week ? (
        <ThisWeek week={data.week} ask={ask} />
      ) : (
        <section className="panel">
          <h2>This week</h2>
          <p className="nothing">
            This week is closed, or has not been opened yet. Opening it happens
            the first time the child&rsquo;s screen is loaded.
          </p>
        </section>
      )}

      <Rewards presets={data.presets} ask={ask} />
      <Payday owed={data.owed} ask={ask} />
      <SavingsPanel savings={data.savings} ask={ask} />
      <Chores chores={data.chores} schemeSettings={data.schemeSettings} ask={ask} />
      <ClosedWeeks weeks={data.weeks} />

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
