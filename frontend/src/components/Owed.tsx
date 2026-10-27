/**
 * What has been settled and not yet handed over — and, kept apart from it,
 * the savings match waiting to go into the bank.
 *
 * The other half of the money on the wall: the big card says what this week is
 * heading for, this says what earlier weeks already came to and nobody has
 * paid yet. Read-only, from the same uncredentialed list the parent's Payday
 * panel ticks off — paying is a parent act and happens there, with the PIN.
 *
 * A month the savings match has ended for but nobody has settled is its own
 * line, never added to the cash total: the weeks are handed over as cash,
 * the match goes into the bank account, and the wall must not suggest it is
 * cash. It stays until a parent settles the month (app.services.savings_match
 * .due_months — nothing settles itself).
 *
 * It stays on screen when there is nothing at all. "All paid up" is a fact
 * worth reading, and a column that comes and goes would shift the week
 * beside it.
 */

import type { DueMonth } from '../api'
import type { Owed as OwedWeek } from '../parentApi'
import { money } from '../api'
import { interestLine, interestTotalLine, shortDate } from '../words'

export function Owed({ owed, due = [] }: { owed: OwedWeek[]; due?: DueMonth[] }) {
  const total = owed.reduce((sum, week) => sum + week.owed_pence, 0)
  const interest = interestTotalLine(due.reduce((sum, month) => sum + month.match_pence, 0))
  const anything = owed.length > 0 || due.length > 0

  return (
    <section className={`owed-card ${anything ? 'owed-card-due' : ''}`}>
      <p className="total-label">Owed to you</p>
      {!anything && <p className="owed-card-clear">All paid up</p>}
      {owed.length > 0 && (
        <>
          <p className="owed-card-amount">{money(total)}</p>
          {/* The strip on the 1280 panel has room for the sum and a count,
              not the list; a wider screen shows the list instead. */}
          <p className="owed-card-count">
            {owed.length} {owed.length === 1 ? 'week' : 'weeks'} to hand over
          </p>
          <ul className="owed-card-weeks">
            {owed.map((week) => (
              <li key={week.week_id}>
                <span>
                  {shortDate(week.start_date)} &ndash; {shortDate(week.end_date)}
                </span>
                <strong>{money(week.owed_pence)}</strong>
              </li>
            ))}
          </ul>
        </>
      )}
      {due.length > 0 && (
        // The strip on the 1280 panel has room for one line, as the cash
        // weeks have a total and a count there; elsewhere, each month.
        <p className="owed-interest-total">
          {interest.label} <strong className="owed-interest-amount">{interest.amount}</strong>
        </p>
      )}
      {due.length > 0 && (
        <ul className="owed-interest">
          {due.map((month) => {
            const line = interestLine(month.period_start, month.match_pence)
            return (
              <li key={month.period_start}>
                <span className="owed-interest-label">
                  {line.label} <strong className="owed-interest-amount">{line.amount}</strong>
                </span>{' '}
                <span className="owed-interest-where">{line.where}</span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
