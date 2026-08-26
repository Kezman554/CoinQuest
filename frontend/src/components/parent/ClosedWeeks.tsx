/**
 * Weeks that are closed, rendered as closed.
 *
 * Almost no controls here, and that is deliberate. A settled week is stored,
 * never recalculated: its figures and the names on its lines are copies
 * taken at the moment it closed, so renaming a chore or changing its amount
 * afterwards leaves them exactly as they were. Nothing in the app can edit
 * one — with the single, narrow exception below.
 *
 * Reopening is that exception, and it is kept apart from everything else on
 * this screen on purpose: offered only on the most recent closed week (the
 * only one the server will actually accept), tucked inside that week's own
 * detail rather than sitting next to a total where a stray tap could reach
 * it, and gated by the same PIN dialog as every other act — one that says
 * plainly, before it happens, that a payment already made is being reversed
 * and the money may already be in his hand.
 */

import { useEffect, useState } from 'react'
import { money } from '../../api'
import type { SettledWeek, WeekSummary } from '../../parentApi'
import { loadWeek, reopenWeek } from '../../parentApi'
import type { PinAct } from './PinDialog'
import { shortDate } from '../../words'

type Ask = { ask: (act: PinAct) => void }

/** The one closed week the server will actually accept a reopen on — the
 * most recent by start date. Exported so anything offering Reopen (this
 * list, and a screen paging back to a specific week) agrees with the server
 * about which week that is, rather than each working it out separately. */
export function mostRecentClosedWeek(weeks: WeekSummary[]): WeekSummary | null {
  const closed = weeks.filter((week) => week.status !== 'open')
  if (closed.length === 0) return null
  return closed.reduce((latest, week) =>
    week.start_date > latest.start_date ? week : latest,
  )
}

export function ClosedWeeks({ weeks, ask }: Ask & { weeks: WeekSummary[] }) {
  const closed = weeks.filter((week) => week.status !== 'open')
  const [open, setOpen] = useState<number | null>(null)

  if (closed.length === 0) {
    return (
      <section className="panel">
        <h2>Closed weeks</h2>
        <p className="nothing">No week has been closed yet.</p>
      </section>
    )
  }

  // The server accepts a reopen only on the most recent closed week — a week
  // with any closed week after it is refused, by name. Mirrored here so the
  // action is only ever offered where it will actually be accepted.
  const mostRecent = mostRecentClosedWeek(weeks)

  return (
    <section className="panel">
      <h2>Closed weeks</h2>
      <ul className="closed-list">
        {[...closed].reverse().map((week) => (
          <li key={week.week_id}>
            <button
              type="button"
              className="closed-row"
              onClick={() => setOpen(open === week.week_id ? null : week.week_id)}
            >
              <span className="closed-dates">
                {shortDate(week.start_date)} – {shortDate(week.end_date)}
              </span>
              <span className={`tag tag-${week.status}`}>{week.status}</span>
              <span className="closed-total">{money(week.total_pence ?? 0)}</span>
            </button>
            {open === week.week_id && (
              <ClosedWeek
                weekId={week.week_id}
                canReopen={week.week_id === mostRecent?.week_id}
                ask={ask}
              />
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** A closed week's figures, fetched by id — exported so a screen paging
 * back to a specific week (see WeekBrowser) can show the same detail this
 * list already shows on expanding one, rather than a second rendering of
 * the same facts. */
export function ClosedWeek({
  weekId,
  canReopen,
  ask,
}: Ask & { weekId: number; canReopen: boolean }) {
  const [week, setWeek] = useState<SettledWeek | null>(null)

  useEffect(() => {
    void loadWeek(weekId).then(setWeek)
  }, [weekId])

  if (!week) return <p className="nothing">Reading it…</p>

  return (
    <div className="closed-detail">
      <p className="closed-note">
        Closed{week.closed_at ? ` on ${shortDate(week.closed_at.slice(0, 10))}` : ''}.
        These are the figures as they stood, not a recalculation.
      </p>

      {week.void_reason && (
        <p className="closed-void">Voided: {week.void_reason}</p>
      )}

      <dl className="breakdown">
        <div>
          <dt>Base</dt>
          <dd>{money(week.base_pence ?? 0)}</dd>
        </div>
        <div>
          <dt>Chores</dt>
          <dd>{money(week.chore_pay_pence ?? 0)}</dd>
        </div>
        <div>
          <dt>Bonus</dt>
          <dd>{money(week.bonus_pence ?? 0)}</dd>
        </div>
        <div>
          <dt>Rewards</dt>
          <dd>{money(week.reward_pence ?? 0)}</dd>
        </div>
        <div>
          <dt>Total</dt>
          <dd>{money(week.total_pence ?? 0)}</dd>
        </div>
      </dl>

      {week.override_reason && (
        <p className="closed-override">
          Settled on an assignment {week.overridden_by ?? 'a parent'} chose:{' '}
          {week.override_reason}. The app offered{' '}
          {money(week.optimum_total_pence ?? 0)}.
        </p>
      )}

      <p className="closed-paid">
        {week.paid_at
          ? `Paid on ${shortDate(week.paid_at.slice(0, 10))}${
              week.deposited_pence
                ? `, ${money(week.deposited_pence)} into the account`
                : ''
            }.`
          : 'Not paid yet.'}
      </p>

      {week.lines.length > 0 && (
        <table className="ledger">
          <tbody>
            {week.lines.map((line, index) => (
              <tr key={`${line.chore_name}-${index}`}>
                <td>{line.chore_name}</td>
                <td>{line.note ?? line.category}</td>
                <td className="ledger-amount">{money(line.amount_pence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {week.reopenings.length > 0 && (
        <div className="reopening-history">
          <h4>Reopened before</h4>
          <ul>
            {week.reopenings.map((reopening, index) => (
              <li key={index}>
                {shortDate(reopening.reopened_at.slice(0, 10))} by{' '}
                {reopening.reopened_by} — {reopening.reason}. Undid{' '}
                {money(reopening.previous_total_pence)}
                {reopening.was_paid
                  ? `, and reversed ${money(reopening.reversed_deposit_pence)} that had gone into the account.`
                  : '.'}
              </li>
            ))}
          </ul>
        </div>
      )}

      {canReopen && <ReopenWeek week={week} ask={ask} />}
    </div>
  )
}

/** The one deliberate exception to "a closed week has no controls".
 *
 * Offered only on the week the server will actually accept — see the
 * `mostRecent` check above — and confirmed like any permanent act, except
 * this one also has to say, when the week was paid, that the payment is
 * being reversed rather than merely a figure changing.
 */
function ReopenWeek({ week, ask }: Ask & { week: SettledWeek }) {
  const [reason, setReason] = useState('')

  const paidLines = week.paid_at
    ? [
        `This week was already paid${
          week.deposited_pence
            ? `, with ${money(week.deposited_pence)} put into the account`
            : ''
        }. Reopening marks it unpaid again${
          week.deposited_pence
            ? ` and reverses that ${money(week.deposited_pence)} out of the account`
            : ''
        }.`,
        'If money was handed over in person, it is still in his hand — reopening the record does not take it back.',
      ]
    : []

  return (
    <div className="reopen-week">
      <h4>Reopen this week</h4>
      <p className="act-note">
        For a figure agreed on purpose and later found wrong — not for a
        change of mind about the scheme. The week goes back to open, and
        settling it again goes through the ordinary steps: the figure agreed
        is checked against what the week is actually worth then, the same as
        ever.
      </p>
      <div className="act-row">
        <input
          type="text"
          placeholder="Why this week is being reopened"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <button
          type="button"
          className="button button-danger"
          disabled={reason.trim().length === 0}
          onClick={() =>
            ask({
              title: 'Reopen this week',
              summary: `${shortDate(week.start_date)} – ${shortDate(
                week.end_date,
              )}, settled at ${money(week.total_pence ?? 0)}, goes back to open.`,
              lines: [...paidLines, reason.trim()],
              confirmLabel: 'Reopen the week',
              permanent: true,
              run: (pin) =>
                reopenWeek(pin, week.week_id, reason).then(() => {
                  setReason('')
                }),
            })
          }
        >
          Reopen
        </button>
      </div>
    </div>
  )
}
