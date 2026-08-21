/**
 * The chores that belong to the week rather than to a day.
 *
 * Deliberately not laid out like the days above. "Three times before Saturday"
 * is not seven boxes with four of them empty — showing it that way invents an
 * absence on the days it was not done, and the scheme never asked about them.
 * Each occasion is its own tappable slot, and the card counts them.
 *
 * A week-long condition is a third thing again: it has no occasions at all and
 * nothing to tap, because it is judged once when the week is settled.
 */

import type { WeeklyCard } from '../api'
import { money } from '../api'
import { Chore } from './Chore'
import { occasion, progress } from '../words'

type Props = {
  weekly: WeeklyCard[]
  onClaim: (instanceId: number) => void
  busyId: number | null
  deadlineWeekday: string
}

export function Weekly({ weekly, onClaim, busyId, deadlineWeekday }: Props) {
  if (weekly.length === 0) return null

  return (
    <section className="panel">
      <h2>Any time this week</h2>
      <div className="weekly">
        {weekly.map((card) => (
          <div
            key={card.definition_id}
            className={`weekly-card${card.waived ? ' weekly-waived' : ''}`}
          >
            <h3>{card.name}</h3>
            <p className="weekly-side">
              {card.category === 'bonus' && <span className="tag tag-bonus">Bonus</span>}
              <span className="chore-amount">{money(card.amount_pence)}</span>
            </p>

            {card.waived ? (
              <p className="waived">
                <strong>Not this week</strong>
                <span>This one is waived</span>
              </p>
            ) : card.judged_at_settlement ? (
              // Nothing to tap: it is judged once, on the day the week closes.
              <p className="nothing">
                Kept up all week. Checked on {deadlineWeekday}.
              </p>
            ) : (
              <>
                {/* A chore wanted once has no count to keep: "0 of 1 done"
                    next to a button saying "I've done it" is the same fact
                    twice, and the second telling is noise. */}
                {card.required > 1 && (
                  <p className="weekly-progress">{progress(card)}</p>
                )}
                {card.instances.map((instance) => (
                  <Chore
                    key={instance.instance_id}
                    chore={{
                      ...instance,
                      // Wanted once: the card's own heading already names
                      // it, and saying it twice in four inches is clutter on
                      // a screen read from across the room.
                      name: card.required > 1 ? occasion(instance.sequence) : '',
                    }}
                    onClaim={onClaim}
                    busy={busyId === instance.instance_id}
                    showAmount={false}
                  />
                ))}
              </>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
