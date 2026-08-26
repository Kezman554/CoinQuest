/**
 * The open week, and the four things a parent can do to it.
 *
 * Settling and voiding are at the bottom and styled apart from the rest,
 * because they are the two that close a week forever. Everything above them
 * can be corrected by doing something else; those two cannot be corrected at
 * all, and a screen that presents them as one more button in a row is telling
 * the reader something untrue about what they do.
 *
 * The figures panel reads the same optimistic "on track" figure the child's
 * own screen does — a claim counts before it is confirmed, and nothing
 * untouched counts against the week until a parent actually rules it missed.
 * Settling never reads that figure, though: the true, pessimistic proposal —
 * everything still untouched treated as the miss it would become — is
 * fetched fresh the moment Settle is pressed, the same "ask, then show the
 * consequence before the PIN" shape Confirm already uses for the queue. The
 * two figures can honestly differ, and the one that gets agreed to has to be
 * the one that is about to be stored.
 */

import { useState } from 'react'
import { money } from '../../api'
import type { WeekView } from '../../api'
import type { Proposal } from '../../parentApi'
import type { PinAct } from './PinDialog'
import {
  loadProposal,
  markMissed,
  settleWeek,
  voidWeek,
  waiveChoreWeek,
  waiveDay,
} from '../../parentApi'
import { longDate, shortDate } from '../../words'

/** What the acts that open a PIN dialog need: the week, and a way to ask.
 *  They need nothing else — the dialog's own onDone reloads the screen. */
type WeekAct = {
  week: WeekView
  ask: (act: PinAct) => void
}

type Props = WeekAct & {
  /** Reload the screen. Every other act here gets this for free when the PIN
   *  dialog closes; marking a miss no longer opens one, so it says so itself. */
  onDone: () => void
  /** Overrides the heading — used for a reopened week that is not the
   * calendar's current one, so it does not read as "This week". */
  title?: string
}

export function ThisWeek({ week, ask, onDone, title = 'This week' }: Props) {
  const chores = choresOf(week)

  return (
    <section className="panel">
      <h2>
        {title} — {shortDate(week.start_date)} to {shortDate(week.end_date)}
      </h2>

      <div className="figures">
        <Figure label="On track for" value={money(week.totals.total_pence)} big />
        <Figure label="Base" value={money(week.totals.base_pence)} />
        <Figure
          label="Chores"
          value={
            week.totals.chore_pay_awarded
              ? money(week.totals.chore_pay_pence)
              : `${money(week.totals.chore_pay_at_stake_pence)} at risk`
          }
          warn={!week.totals.chore_pay_awarded}
        />
        <Figure label="Bonus" value={money(week.totals.bonus_pence)} />
        {week.totals.ad_hoc_reward_pence > 0 && (
          <Figure
            label="Rewards on top"
            value={money(week.totals.ad_hoc_reward_pence)}
            note="Paid with the week; not part of the settled figure"
          />
        )}
      </div>

      <MarkMissed week={week} onDone={onDone} />
      <Waive week={week} chores={chores} ask={ask} />

      <div className="closing">
        <h3>Closing the week</h3>
        <p className="closing-note">
          Both of these are permanent. A closed week is stored, never
          recalculated, and no later change to the scheme reaches back into it.
        </p>
        <div className="closing-buttons">
          <SettleButton week={week} ask={ask} />
          <VoidWeek week={week} ask={ask} />
        </div>
      </div>
    </section>
  )
}

/** Fetches the true, pessimistic proposal the instant it is pressed, and
 * only then opens the PIN dialog — on that figure, never on the week's own
 * optimistic screen. Mirrors Queue's own "Confirm" exactly: ask what this
 * would actually do, show it, then ask for the PIN. */
function SettleButton({ week, ask }: WeekAct) {
  const [checking, setChecking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const settle = async () => {
    setChecking(true)
    setProblem(null)
    try {
      const proposal = await loadProposal(week.week_id)
      ask({
        title: 'Settle this week',
        summary: `${shortDate(proposal.start_date)} to ${shortDate(
          proposal.end_date,
        )} settles at ${money(proposal.total_pence)}.`,
        lines: settlementLines(proposal, week.totals.ad_hoc_reward_pence),
        confirmLabel: `Settle at ${money(proposal.total_pence)}`,
        permanent: true,
        run: (pin) =>
          settleWeek(pin, week.week_id, proposal.total_pence).then(() => undefined),
      })
    } catch (error) {
      setProblem((error as Error).message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="settle-button">
      <button type="button" className="button button-do" onClick={settle} disabled={checking}>
        {checking ? 'Working out the true figure…' : 'Settle'}
      </button>
      {problem && (
        <p className="dialog-error" role="alert">
          {problem}
        </p>
      )}
    </div>
  )
}

function Figure({
  label,
  value,
  big,
  warn,
  note,
}: {
  label: string
  value: string
  big?: boolean
  warn?: boolean
  note?: string
}) {
  return (
    <div className={`figure${big ? ' figure-big' : ''}${warn ? ' figure-warn' : ''}`}>
      <span className="figure-label">{label}</span>
      <span className="figure-value">{value}</span>
      {note && <span className="figure-note">{note}</span>}
    </div>
  )
}

function settlementLines(proposal: Proposal, adHocRewardPence: number): string[] {
  const lines = [
    `Base ${money(proposal.base_pence)}, chores ${money(
      proposal.chore_pay_pence,
    )}, bonus ${money(proposal.bonus_pence)}.`,
  ]
  if (!proposal.chore_pay_awarded && proposal.chore_pay_at_stake_pence > 0) {
    lines.push(
      `The chore money is not awarded: ${money(
        proposal.chore_pay_at_stake_pence,
      )} is lost to what is still outstanding.`,
    )
  }
  if (adHocRewardPence > 0) {
    lines.push(`${money(adHocRewardPence)} of rewards is owed on top and is paid with the week.`)
  }
  return lines
}

/**
 * Ruling a chore missed, which is what makes the recovery window usable.
 *
 * The one act on this screen with no PIN dialog in front of it. It pays
 * nothing and can be cleared again from either screen — see api.ts's
 * clearMiss, which does ask — and asking here would be asking for a
 * credential the API no longer checks, which teaches a parent something
 * untrue about what is guarded. The same control is on the child's day tiles
 * now, which is where it will actually be used; this one stays because it
 * reaches a reopened week and a chore with no day attached to it.
 */
function MarkMissed({ week, onDone }: { week: WeekView; onDone: () => void }) {
  const [instanceId, setInstanceId] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const candidates = choreInstances(week).filter(
    (chore) => chore.state === 'untouched' || chore.state === 'claimed',
  )

  if (candidates.length === 0) return null

  const chosen = candidates.find(
    (chore) => String(chore.instance_id) === instanceId,
  )

  const mark = async () => {
    if (!chosen) return
    setBusy(true)
    setProblem(null)
    try {
      await markMissed(chosen.instance_id as number)
      setInstanceId('')
      onDone()
    } catch (error) {
      setProblem((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="act">
      <h3>Mark something missed</h3>
      <p className="act-note">
        Told today that yesterday was missed, the child has the rest of the week
        to work it back. Leaving it to settlement does not. No PIN: it pays
        nothing, and either screen can clear it again with one.
      </p>
      <div className="act-row">
        <select value={instanceId} onChange={(e) => setInstanceId(e.target.value)}>
          <option value="">Choose a chore…</option>
          {candidates.map((chore) => (
            <option key={chore.instance_id} value={String(chore.instance_id)}>
              {chore.name}
              {chore.due_date ? ` — ${shortDate(chore.due_date)}` : ''}
              {chore.state === 'claimed' ? ' (claimed)' : ''}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="button"
          disabled={!chosen || busy}
          onClick={() => void mark()}
        >
          {busy ? 'Marking…' : 'Mark missed'}
        </button>
      </div>
      {problem && (
        <p className="dialog-error" role="alert">
          {problem}
        </p>
      )}
    </div>
  )
}

/** Waiving: a day away, or one chore excused for this week. */
function Waive({
  week,
  chores,
  ask,
}: WeekAct & { chores: { definition_id: number; name: string }[] }) {
  const [day, setDay] = useState('')
  const [dayReason, setDayReason] = useState('')
  const [choreId, setChoreId] = useState('')
  const [choreReason, setChoreReason] = useState('')

  const chore = chores.find((item) => String(item.definition_id) === choreId)

  return (
    <div className="act">
      <h3>Waive</h3>
      <p className="act-note">
        A waiver is not forgiveness for a miss: it means the occasion never
        counted. A weekly count scales down by the days away rather than being
        failed.
      </p>

      <div className="act-row">
        <select value={day} onChange={(event) => setDay(event.target.value)}>
          <option value="">Waive a day…</option>
          {week.days
            .filter((item) => !item.waived)
            .map((item) => (
              <option key={item.day} value={item.day}>
                {item.weekday} {shortDate(item.day)}
              </option>
            ))}
        </select>
        <input
          type="text"
          placeholder="Why (e.g. away at Grandma's)"
          value={dayReason}
          onChange={(event) => setDayReason(event.target.value)}
        />
        <button
          type="button"
          className="button"
          disabled={!day}
          onClick={() =>
            ask({
              title: 'Waive a day',
              summary: `${longDate(day)} is not assessed at all.`,
              lines: [
                'Anything untouched that day stops being asked for. Anything already confirmed stays confirmed.',
              ],
              confirmLabel: 'Waive the day',
              run: (pin) =>
                waiveDay(pin, day, dayReason).then(() => {
                  setDay('')
                  setDayReason('')
                }),
            })
          }
        >
          Waive day
        </button>
      </div>

      <div className="act-row">
        <select value={choreId} onChange={(event) => setChoreId(event.target.value)}>
          <option value="">Waive a chore for this week…</option>
          {chores.map((item) => (
            <option key={item.definition_id} value={String(item.definition_id)}>
              {item.name}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Why (e.g. the hoover is broken)"
          value={choreReason}
          onChange={(event) => setChoreReason(event.target.value)}
        />
        <button
          type="button"
          className="button"
          disabled={!chore}
          onClick={() =>
            chore &&
            ask({
              title: 'Waive a chore for this week',
              summary: `${chore.name} is not asked for this week.`,
              lines: ['It stops counting toward the chore money, this week only.'],
              confirmLabel: 'Waive it',
              run: (pin) =>
                waiveChoreWeek(pin, week.week_id, chore.definition_id, choreReason).then(
                  () => {
                    setChoreId('')
                    setChoreReason('')
                  },
                ),
            })
          }
        >
          Waive chore
        </button>
      </div>
    </div>
  )
}

function VoidWeek({ week, ask }: WeekAct) {
  const [reason, setReason] = useState('')

  return (
    <div className="void-week">
      <input
        type="text"
        placeholder="Why this week is void"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
      <button
        type="button"
        className="button button-danger"
        disabled={reason.trim().length === 0}
        onClick={() =>
          ask({
            title: 'Void this week',
            summary: 'The week pays nothing at all.',
            lines: [
              'The base, the chore money and the bonuses all go.',
              'The record of what was done is kept, and rewards entered against the week are still his.',
            ],
            confirmLabel: 'Void the week',
            permanent: true,
            run: (pin) =>
              voidWeek(pin, week.week_id, reason).then(() => {
                setReason('')
              }),
          })
        }
      >
        Void the week
      </button>
    </div>
  )
}

function choreInstances(week: WeekView) {
  const cards = week.days.flatMap((day) => day.chores)
  week.weekly.forEach((card) => cards.push(...card.instances))
  return cards
}

/** One entry per chore the week asks for, for the waive-a-chore control. */
function choresOf(week: WeekView): { definition_id: number; name: string }[] {
  const seen = new Map<number, string>()
  choreInstances(week).forEach((chore) => seen.set(chore.definition_id, chore.name))
  week.weekly.forEach((card) => seen.set(card.definition_id, card.name))
  return [...seen.entries()]
    .map(([definition_id, name]) => ({ definition_id, name }))
    .sort((a, b) => a.name.localeCompare(b.name))
}
