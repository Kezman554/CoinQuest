/**
 * The pending queue: rule on each claim, then confirm the lot once.
 *
 * Two buttons in this section, and only one of them acts. Confirm is the
 * act, matching every other act on this screen: rule on the claims, press
 * Confirm, read what it does, authorise it with a PIN. The consequence
 * still comes before the PIN — it lives in the dialog that Confirm opens,
 * the same place Settle, Void and every other act on this screen already
 * shows theirs. A parent who has just ticked three chores sees Confirm
 * immediately; nothing here depends on them noticing a differently-labelled
 * button first.
 *
 * Approve all (Session AR) is staging only: it presses Yes on every claim
 * with no ruling yet, in the same rulings the per-row buttons write, and
 * sends nothing, asks for no PIN and calls no route of its own. Most weeks
 * every claim is approved, and a click per row was a lot of clicks for one
 * decision. A refusal already staged is left alone, and every row can still
 * be switched or cleared afterwards. It sits at the head of the queue, not
 * beside Confirm, so the two are never read as one another. Once every
 * claim has a ruling it stays where it is, greyed, saying "Nothing left to
 * approve" (DESIGN.md: a forbidden control keeps its place and says why) —
 * which also keeps the queue from jumping under a finger on the wall the
 * moment the last claim is ruled. Only an empty queue has no button, since
 * there is no queue for it to sit in.
 *
 * The batch is still submitted once, with one PIN, and either all of it
 * applies or none does — nothing about that changed, only where the
 * consequence is read.
 *
 * Grouped by week, most recent first. This became necessary the moment a new
 * week started with claims still waiting on the one before it: a flat list
 * read as though everything belonged to now, and a claim from last Saturday
 * night sat unlabelled beside one from this morning. The grouping is
 * presentation only — a ruling on a claim from any week joins the same one
 * batch, submitted together with the same single PIN, exactly as before.
 */

import { useCallback, useId, useState } from 'react'
import { money } from '../../api'
import type { Consequence, DecisionIn, Pending, Ruling } from '../../parentApi'
import { previewReview } from '../../parentApi'
import { approveAllNote, batchAction, pendingLabel, waitingFor, weekLabel } from '../../parentWords'
import { Why } from '../Why'

type Props = {
  queue: Pending[]
  onSubmit: (decisions: DecisionIn[], effects: Consequence[]) => void
}

export function Queue({ queue, onSubmit }: Props) {
  const [rulings, setRulings] = useState<Record<number, Ruling>>({})
  const [problem, setProblem] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const whyId = useId()
  const approveId = useId()

  const decisions: DecisionIn[] = Object.entries(rulings).map(
    ([instance_id, decision]) => ({ instance_id: Number(instance_id), decision }),
  )

  const rule = useCallback((instanceId: number, decision: Ruling) => {
    // A stale refusal is worse than none: it describes a batch that no
    // longer matches the rulings on screen. Cleared here, in the event that
    // caused it, rather than from an effect watching the rulings.
    setProblem(null)
    setRulings((current) => {
      const next = { ...current }
      if (next[instanceId] === decision) delete next[instanceId]
      else next[instanceId] = decision
      return next
    })
  }, [])

  // Yes on every claim without a ruling; a refusal or an earlier Yes is
  // left exactly as it is. Nothing is sent — Confirm still does that.
  const approveAll = useCallback(() => {
    setProblem(null)
    setRulings((current) => {
      const next = { ...current }
      for (const claim of queue) {
        if (!(claim.instance_id in next)) next[claim.instance_id] = 'confirm'
      }
      return next
    })
  }, [queue])

  // Reads the consequence and hands it straight to the PIN dialog — the
  // same fetch the old two-click version made, just no longer requiring a
  // separate click to see its result before the button that actually
  // commits appears.
  const confirm = useCallback(async () => {
    setChecking(true)
    setProblem(null)
    try {
      const effects = await previewReview(decisions)
      onSubmit(decisions, effects)
    } catch (error) {
      setProblem((error as Error).message)
    } finally {
      setChecking(false)
    }
  }, [decisions, onSubmit])

  if (queue.length === 0) {
    return (
      <section className="panel">
        <h2>Claims waiting</h2>
        <p className="nothing">Nothing is waiting to be checked.</p>
      </section>
    )
  }

  const confirmed = decisions.filter((d) => d.decision === 'confirm').length
  const rejected = decisions.length - confirmed

  const unruled = queue.filter((claim) => !(claim.instance_id in rulings)).length

  const groups = groupByWeek(queue)

  return (
    <section className="panel">
      <h2>Claims waiting ({queue.length})</h2>

      <div className="queue-tools">
        <button
          type="button"
          className="button button-quiet"
          onClick={approveAll}
          disabled={unruled === 0}
          aria-describedby={approveId}
        >
          Approve all
        </button>
        {/* One line in one place, enabled or not: what it stages, or why
            there is nothing to. Its height does not change with the state. */}
        <p className="queue-tools-note" id={approveId}>
          {unruled === 0 ? 'Nothing left to approve.' : approveAllNote(unruled, queue.length)}
        </p>
      </div>

      {groups.map((group) => (
        <div className="queue-week" key={group.week_id}>
          <h3 className="queue-week-heading">
            {weekLabel(group.week_start_date, group.week_end_date)}
          </h3>
          <ul className="queue">
            {group.claims.map((claim) => (
              <li
                key={claim.instance_id}
                className={`queue-item ruled-${rulings[claim.instance_id] ?? 'none'}`}
              >
                <div className="queue-what">
                  <span className="queue-name">{pendingLabel(claim)}</span>
                  <span className="queue-meta">
                    {money(claim.amount_pence)}
                    {claim.category === 'bonus' && <span className="tag tag-bonus">Bonus</span>}
                    <span className="queue-when">{waitingFor(claim.claimed_at)}</span>
                    {claim.rejection_count > 0 && (
                      <span className="tag tag-again">
                        Refused before ({claim.rejection_count})
                      </span>
                    )}
                  </span>
                </div>
                <div className="queue-rule">
                  <button
                    type="button"
                    className={`button button-confirm button-yes${
                      rulings[claim.instance_id] === 'confirm' ? ' chosen' : ''
                    }`}
                    aria-pressed={rulings[claim.instance_id] === 'confirm'}
                    onClick={() => rule(claim.instance_id, 'confirm')}
                  >
                    Yes
                  </button>
                  <button
                    type="button"
                    className={`button button-danger button-no${
                      rulings[claim.instance_id] === 'reject' ? ' chosen' : ''
                    }`}
                    aria-pressed={rulings[claim.instance_id] === 'reject'}
                    onClick={() => rule(claim.instance_id, 'reject')}
                  >
                    No
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}

      {/* Confirm stays where it is before anything is ruled, disabled and
          saying why, rather than appearing only once there is a batch. */}
      <div className="batch">
        {decisions.length > 0 && (
          <p className="batch-action">{batchAction(confirmed, rejected)}</p>
        )}

        {problem && (
          <p className="dialog-error" role="alert">
            {problem}
          </p>
        )}

        <button
          type="button"
          className="button button-confirm"
          onClick={confirm}
          disabled={checking || decisions.length === 0}
          aria-describedby={decisions.length === 0 ? whyId : undefined}
        >
          {checking ? 'Working it out…' : 'Confirm'}
        </button>
        <Why
          id={whyId}
          reason={decisions.length === 0 ? 'Rule on a claim to build a batch.' : null}
        />
      </div>
    </section>
  )
}

type WeekGroup = {
  week_id: number
  week_start_date: string
  week_end_date: string
  claims: Pending[]
}

/** One heading per week, most recent first. Within a week, the server's own
 * oldest-first order is kept — the order a parent would naturally work
 * through a single week's claims in. */
function groupByWeek(queue: Pending[]): WeekGroup[] {
  const byWeek = new Map<number, WeekGroup>()
  for (const claim of queue) {
    let group = byWeek.get(claim.week_id)
    if (!group) {
      group = {
        week_id: claim.week_id,
        week_start_date: claim.week_start_date,
        week_end_date: claim.week_end_date,
        claims: [],
      }
      byWeek.set(claim.week_id, group)
    }
    group.claims.push(claim)
  }
  return [...byWeek.values()].sort((a, b) =>
    b.week_start_date.localeCompare(a.week_start_date),
  )
}
