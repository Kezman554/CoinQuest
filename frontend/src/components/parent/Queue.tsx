/**
 * The pending queue: rule on each claim, then submit the lot once.
 *
 * Two stages on purpose. Working through the list decides nothing — a ruling
 * here is a mark against an item and no request has been made. The batch is
 * submitted once, with one PIN, and either all of it applies or none does,
 * which is what stops a parent ending up half-committed to a list they now
 * have to reconstruct from memory.
 *
 * Between the two stages sits the consequence: what agreeing to this actually
 * does to the week. It is fetched from the server rather than worked out here,
 * because the only way to be sure the preview matches the outcome is for it to
 * be the same code over the same data.
 */

import { useCallback, useState } from 'react'
import { money } from '../../api'
import type { Consequence, DecisionIn, Pending, Ruling } from '../../parentApi'
import { previewReview } from '../../parentApi'
import {
  batchAction,
  consequenceLines,
  pendingLabel,
  waitingFor,
  weekLabel,
} from '../../parentWords'

type Props = {
  queue: Pending[]
  onSubmit: (decisions: DecisionIn[], effects: Consequence[]) => void
}

export function Queue({ queue, onSubmit }: Props) {
  const [rulings, setRulings] = useState<Record<number, Ruling>>({})
  const [effects, setEffects] = useState<Consequence[] | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)

  const decisions: DecisionIn[] = Object.entries(rulings).map(
    ([instance_id, decision]) => ({ instance_id: Number(instance_id), decision }),
  )

  const rule = useCallback((instanceId: number, decision: Ruling) => {
    // Any change to the rulings makes an existing consequence stale, and a
    // stale consequence is worse than none: it describes a batch nobody is
    // about to submit. Cleared here, in the event that caused it, rather than
    // from an effect watching the rulings — same result, one render fewer,
    // and it cannot fire on a re-render nobody asked for.
    setEffects(null)
    setProblem(null)
    setRulings((current) => {
      const next = { ...current }
      if (next[instanceId] === decision) delete next[instanceId]
      else next[instanceId] = decision
      return next
    })
  }, [])

  const check = useCallback(async () => {
    setChecking(true)
    try {
      setEffects(await previewReview(decisions))
      setProblem(null)
    } catch (error) {
      setProblem((error as Error).message)
      setEffects(null)
    } finally {
      setChecking(false)
    }
  }, [decisions])

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

  return (
    <section className="panel">
      <h2>Claims waiting ({queue.length})</h2>

      <ul className="queue">
        {queue.map((claim) => (
          <li key={claim.instance_id} className={`queue-item ruled-${rulings[claim.instance_id] ?? 'none'}`}>
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
                className={`button button-yes${
                  rulings[claim.instance_id] === 'confirm' ? ' chosen' : ''
                }`}
                onClick={() => rule(claim.instance_id, 'confirm')}
              >
                Yes
              </button>
              <button
                type="button"
                className={`button button-no${
                  rulings[claim.instance_id] === 'reject' ? ' chosen' : ''
                }`}
                onClick={() => rule(claim.instance_id, 'reject')}
              >
                No
              </button>
            </div>
          </li>
        ))}
      </ul>

      {decisions.length === 0 ? (
        <p className="nothing">Rule on a claim to build a batch.</p>
      ) : (
        <div className="batch">
          <p className="batch-action">{batchAction(confirmed, rejected)}</p>

          {problem && (
            <p className="dialog-error" role="alert">
              {problem}
            </p>
          )}

          {effects === null ? (
            <button
              type="button"
              className="button button-do"
              onClick={check}
              disabled={checking}
            >
              {checking ? 'Working it out…' : 'What does this do?'}
            </button>
          ) : (
            <>
              {effects.map((effect) => (
                <div key={effect.week_id} className="effect">
                  <h3>{weekLabel(effect.start_date, effect.end_date)}</h3>
                  <ul>
                    {consequenceLines(effect).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              ))}
              {effects.length === 0 && (
                <p className="nothing">
                  This batch touches no open week, so it changes no figures.
                </p>
              )}
              <button
                type="button"
                className="button button-do"
                onClick={() => onSubmit(decisions, effects)}
              >
                Submit with PIN
              </button>
            </>
          )}
        </div>
      )}
    </section>
  )
}
