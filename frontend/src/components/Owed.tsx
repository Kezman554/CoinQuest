/**
 * What has been settled and not yet handed over.
 *
 * The other half of the money on the wall: the big card says what this week is
 * heading for, this says what earlier weeks already came to and nobody has
 * paid yet. Read-only, from the same uncredentialed list the parent's Payday
 * panel ticks off — paying is a parent act and happens there, with the PIN.
 *
 * It stays on screen when the list is empty. "All paid up" is a fact worth
 * reading, and a column that comes and goes would shift the week beside it.
 */

import type { Owed as OwedWeek } from '../parentApi'
import { money } from '../api'
import { shortDate } from '../words'

export function Owed({ owed }: { owed: OwedWeek[] }) {
  const total = owed.reduce((sum, week) => sum + week.owed_pence, 0)

  return (
    <section className={`owed-card ${owed.length > 0 ? 'owed-card-due' : ''}`}>
      <p className="total-label">Owed to you</p>
      {owed.length === 0 ? (
        <p className="owed-card-clear">All paid up</p>
      ) : (
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
    </section>
  )
}
