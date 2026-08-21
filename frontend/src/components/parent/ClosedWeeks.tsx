/**
 * Weeks that are closed, rendered as closed.
 *
 * There are no controls here at all, and that is the point rather than an
 * omission. A settled week is stored, never recalculated: its figures and the
 * names on its lines are copies taken at the moment it closed, so renaming a
 * chore or changing its amount afterwards leaves them exactly as they were.
 * Nothing in the app can edit one, so nothing here offers to.
 *
 * A correction, if one is ever needed, is a new row somewhere else — never an
 * edit to this.
 */

import { useEffect, useState } from 'react'
import { money } from '../../api'
import type { SettledWeek, WeekSummary } from '../../parentApi'
import { loadWeek } from '../../parentApi'
import { shortDate } from '../../words'

export function ClosedWeeks({ weeks }: { weeks: WeekSummary[] }) {
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
            {open === week.week_id && <ClosedWeek weekId={week.week_id} />}
          </li>
        ))}
      </ul>
    </section>
  )
}

function ClosedWeek({ weekId }: { weekId: number }) {
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
    </div>
  )
}
