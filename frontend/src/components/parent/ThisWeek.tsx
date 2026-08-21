/**
 * The open week, and the four things a parent can do to it.
 *
 * Settling and voiding are at the bottom and styled apart from the rest,
 * because they are the two that close a week forever. Everything above them
 * can be corrected by doing something else; those two cannot be corrected at
 * all, and a screen that presents them as one more button in a row is telling
 * the reader something untrue about what they do.
 *
 * The settle button carries the figure it is about to agree to, in the label.
 * The API refuses a settlement whose agreed figure no longer matches the
 * proposal, so an amount read here and agreed after somebody else confirmed
 * something is refused rather than quietly settled on a different number —
 * but the parent should be reading the figure they are agreeing, not a word.
 */

import { useState } from 'react'
import { money } from '../../api'
import type { WeekView } from '../../api'
import type { PinAct } from './PinDialog'
import {
  markMissed,
  settleWeek,
  voidWeek,
  waiveChoreWeek,
  waiveDay,
} from '../../parentApi'
import { longDate, shortDate } from '../../words'

type Props = {
  week: WeekView
  ask: (act: PinAct) => void
}

export function ThisWeek({ week, ask }: Props) {
  const chores = choresOf(week)

  return (
    <section className="panel">
      <h2>
        This week — {shortDate(week.start_date)} to {shortDate(week.end_date)}
      </h2>

      <div className="figures">
        <Figure label="On track to settle at" value={money(week.totals.total_pence)} big />
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

      <MarkMissed week={week} ask={ask} />
      <Waive week={week} chores={chores} ask={ask} />

      <div className="closing">
        <h3>Closing the week</h3>
        <p className="closing-note">
          Both of these are permanent. A closed week is stored, never
          recalculated, and no later change to the scheme reaches back into it.
        </p>
        <div className="closing-buttons">
          <button
            type="button"
            className="button button-do"
            onClick={() =>
              ask({
                title: 'Settle this week',
                summary: `${shortDate(week.start_date)} to ${shortDate(
                  week.end_date,
                )} settles at ${money(week.totals.total_pence)}.`,
                lines: settlementLines(week),
                confirmLabel: `Settle at ${money(week.totals.total_pence)}`,
                permanent: true,
                run: (pin) =>
                  settleWeek(pin, week.week_id, week.totals.total_pence).then(
                    () => undefined,
                  ),
              })
            }
          >
            Settle at {money(week.totals.total_pence)}
          </button>
          <VoidWeek week={week} ask={ask} />
        </div>
      </div>
    </section>
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

function settlementLines(week: WeekView): string[] {
  const lines = [
    `Base ${money(week.totals.base_pence)}, chores ${money(
      week.totals.chore_pay_pence,
    )}, bonus ${money(week.totals.bonus_pence)}.`,
  ]
  if (!week.totals.chore_pay_awarded && week.totals.chore_pay_at_stake_pence > 0) {
    lines.push(
      `The chore money is not awarded: ${money(
        week.totals.chore_pay_at_stake_pence,
      )} is lost to what is still outstanding.`,
    )
  }
  if (week.totals.ad_hoc_reward_pence > 0) {
    lines.push(
      `${money(
        week.totals.ad_hoc_reward_pence,
      )} of rewards is owed on top and is paid with the week.`,
    )
  }
  return lines
}

/** Ruling a chore missed, which is what makes the recovery window usable. */
function MarkMissed({ week, ask }: Props) {
  const [instanceId, setInstanceId] = useState('')
  const candidates = choreInstances(week).filter(
    (chore) => chore.state === 'untouched' || chore.state === 'claimed',
  )

  if (candidates.length === 0) return null

  const chosen = candidates.find(
    (chore) => String(chore.instance_id) === instanceId,
  )

  return (
    <div className="act">
      <h3>Mark something missed</h3>
      <p className="act-note">
        Told today that yesterday was missed, the child has the rest of the week
        to work it back. Leaving it to settlement does not.
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
          disabled={!chosen}
          onClick={() =>
            chosen &&
            ask({
              title: 'Mark it missed',
              summary: `${chosen.name}${
                chosen.due_date ? ` on ${longDate(chosen.due_date)}` : ''
              } is ruled missed.`,
              lines: [
                'The child can still put it right with a bonus chore before the week ends.',
              ],
              confirmLabel: 'Mark missed',
              run: (pin) =>
                markMissed(pin, chosen.instance_id as number).then(() => {
                  setInstanceId('')
                }),
            })
          }
        >
          Mark missed
        </button>
      </div>
    </div>
  )
}

/** Waiving: a day away, or one chore excused for this week. */
function Waive({
  week,
  chores,
  ask,
}: Props & { chores: { definition_id: number; name: string }[] }) {
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

function VoidWeek({ week, ask }: Props) {
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
