/**
 * The day-by-day chores, one block per day of the week.
 *
 * Every day of the week is here, including the ones nothing is asked of and
 * including the ones that were waived. Dropping a day would make the week look
 * six days long, and a waived day shown empty would read as a day on which
 * nothing was done — which is the one thing it is not.
 */

import type { DayCard, InstanceCard } from '../api'
import { Chore } from './Chore'
import { longDate } from '../words'

type Props = {
  days: DayCard[]
  onClaim: (instanceId: number) => void
  busyId: number | null
}

export function Days({ days, onClaim, busyId }: Props) {
  return (
    <section className="panel">
      <h2>Every day</h2>
      <div className="days">
        {days.map((day) => (
          <Day key={day.day} day={day} onClaim={onClaim} busyId={busyId} />
        ))}
      </div>
    </section>
  )
}

function Day({
  day,
  onClaim,
  busyId,
}: {
  day: DayCard
  onClaim: (instanceId: number) => void
  busyId: number | null
}) {
  const classes = ['day']
  if (day.is_today) classes.push('day-today')
  if (day.waived) classes.push('day-waived')
  if (day.is_past && !day.is_today) classes.push('day-past')

  return (
    <div className={classes.join(' ')}>
      <h3>
        {day.weekday}
        {day.is_today && <span className="tag tag-today">Today</span>}
      </h3>
      <p className="day-date">{longDate(day.day)}</p>

      {day.waived ? (
        // A day away. Not an absence, and not something to be put right.
        <p className="waived">
          <strong>Day off</strong>
          <span>{day.waiver_reason ?? 'Nothing was needed today'}</span>
        </p>
      ) : day.chores.length === 0 ? (
        <p className="nothing">Nothing due</p>
      ) : (
        day.chores.map((chore: InstanceCard) => (
          <Chore
            key={chore.instance_id}
            chore={chore}
            onClaim={onClaim}
            busy={busyId === chore.instance_id}
          />
        ))
      )}
    </div>
  )
}
