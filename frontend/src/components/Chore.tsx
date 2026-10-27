/**
 * One chore, with at most one button on it — and, on a missed day tile, the
 * way back set deliberately apart from it.
 *
 * The button is the whole row rather than a small control at the end of it:
 * this is tapped by a child in a hurry, on a wall screen, and a target the
 * size of a fingertip is a target that gets mis-hit and undone again.
 *
 * The undo is the opposite shape on purpose. It is small and sits under the
 * row rather than being the row. Marking a miss is no longer offered here at
 * all — it is a parent's act, on the parent screen — but taking one back
 * still is, because this is where the missed chore is seen, and it opens the
 * parents' own PIN dialog. The server refuses the clear without the PIN
 * whatever this file renders; see app/routers/claims.py.
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
  /** Absent everywhere except the day tiles of an open week — which is
   *  what keeps a settled week being paged back through read-only. */
  onClearMiss?: (chore: InstanceCard) => void
}

export function Chore({
  chore,
  onClaim,
  busy,
  showAmount = true,
  onClearMiss,
}: Props) {
  const note = rejectionNote(chore)
  const label = stateLabel(chore)

  const body = (
    <>
      {chore.name && <span className="chore-name">{chore.name}</span>}
      {/* A basic chore pays as part of the flat weekly chore pot, never on
          its own — a figure beside it reads as "this one pays £X", which
          isn't true of any single basic chore, so it gets no chore-side at
          all. Bonus and reward amounts are real per-chore figures and keep
          showing exactly as before. */}
      {showAmount && chore.category !== 'basic' && (
        <span className="chore-side">
          {chore.category === 'bonus' && <span className="tag tag-bonus">Bonus</span>}
          {chore.category === 'reward' && <span className="tag tag-reward">Reward</span>}
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

  const control = clearControl(chore, onClearMiss)
  if (!control) return row

  return (
    <div className="chore-row">
      {row}
      {control}
    </div>
  )
}

/**
 * Only a miss a person marked can be cleared. One settlement worked out
 * belongs to a week already closed, and offering to undo it would be offering
 * something the API is right to refuse.
 */
function clearControl(chore: InstanceCard, onClearMiss?: (chore: InstanceCard) => void) {
  if (chore.instance_id === null || chore.state !== 'missed') return null
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
