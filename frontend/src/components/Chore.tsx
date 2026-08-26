/**
 * One chore, with at most one button on it — and, on the day tiles, a second
 * control set deliberately apart from it.
 *
 * The button is the whole row rather than a small control at the end of it:
 * this is tapped by a child in a hurry, on a wall screen, and a target the
 * size of a fingertip is a target that gets mis-hit and undone again.
 *
 * The missed control is the opposite shape on purpose. It is small, it sits
 * under the row rather than being the row, and it is worded as a statement
 * about the chore rather than as an instruction. A parent walking past has to
 * be able to hit it in a couple of seconds; a child in a hurry must not hit it
 * by accident while reaching for the thing that says "I've done it".
 *
 * Which control appears is the authorisation split, and only half of it: the
 * server refuses the clear without the PIN whatever this file renders. See
 * app/routers/claims.py. Marking is a tap because it only ever costs him
 * money; clearing opens the parents' own PIN dialog because it gives it back.
 */

import type { InstanceCard } from '../api'
import { money } from '../api'
import { rejectionNote, stateLabel } from '../words'

type Props = {
  chore: InstanceCard
  onClaim: (instanceId: number) => void
  busy: boolean
  /** Off for one occasion of a chore paid once for the whole week: the
   *  amount belongs to the card around it, not to each slot inside it. */
  showAmount?: boolean
  /** Both absent everywhere except the day tiles of the current, open week —
   *  which is what keeps a week being paged back through read-only. */
  onMissed?: (instanceId: number) => void
  onClearMiss?: (chore: InstanceCard) => void
}

export function Chore({
  chore,
  onClaim,
  busy,
  showAmount = true,
  onMissed,
  onClearMiss,
}: Props) {
  const note = rejectionNote(chore)
  const label = stateLabel(chore)

  const body = (
    <>
      {chore.name && <span className="chore-name">{chore.name}</span>}
      {showAmount && (
        <span className="chore-side">
          {chore.category === 'bonus' && <span className="tag tag-bonus">Bonus</span>}
          <span className="chore-amount">{money(chore.amount_pence)}</span>
        </span>
      )}
    </>
  )

  const claimable = chore.can_claim && chore.instance_id !== null

  const row = claimable ? (
    <button
      type="button"
      className="chore chore-claimable"
      disabled={busy}
      onClick={() => onClaim(chore.instance_id as number)}
    >
      {body}
      <span className="chore-state">{busy ? 'Sending…' : label}</span>
      {note && <span className="chore-note">{note}</span>}
    </button>
  ) : (
    <div className={`chore chore-${chore.state}`}>
      {body}
      <span className="chore-state">{label}</span>
    </div>
  )

  const control = missedControl(chore, busy, onMissed, onClearMiss)
  if (!control) return row

  return (
    <div className="chore-row">
      {row}
      {control}
    </div>
  )
}

/**
 * The one control that changes, and the rule about which way it points.
 *
 * Confirmed work is never offered a Missed button: confirmed work is not taken
 * back this way, and the server refuses it too. A miss that settlement worked
 * out rather than a person marked gets no Clear button either — that one
 * belongs to a week already closed, and offering to undo it would be offering
 * something the API is right to refuse.
 */
function missedControl(
  chore: InstanceCard,
  busy: boolean,
  onMissed?: (instanceId: number) => void,
  onClearMiss?: (chore: InstanceCard) => void,
) {
  if (chore.instance_id === null) return null

  if (chore.state === 'missed') {
    if (!onClearMiss || chore.miss_origin !== 'parent_marked') return null
    return (
      <button
        type="button"
        className="chore-control chore-control-undo"
        onClick={() => onClearMiss(chore)}
      >
        Not missed after all
      </button>
    )
  }

  if (chore.state === 'confirmed' || !onMissed) return null

  return (
    <button
      type="button"
      className="chore-control"
      disabled={busy}
      onClick={() => onMissed(chore.instance_id as number)}
    >
      Missed
    </button>
  )
}
