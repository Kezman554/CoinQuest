/**
 * One chore, with at most one button on it.
 *
 * The button is the whole row rather than a small control at the end of it:
 * this is tapped by a child in a hurry, on a wall screen, and a target the
 * size of a fingertip is a target that gets mis-hit and undone again.
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
}

export function Chore({ chore, onClaim, busy, showAmount = true }: Props) {
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

  if (!chore.can_claim || chore.instance_id === null) {
    return (
      <div className={`chore chore-${chore.state}`}>
        {body}
        <span className="chore-state">{label}</span>
      </div>
    )
  }

  return (
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
  )
}
