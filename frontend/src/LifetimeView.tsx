/**
 * Oliver's lifetime page: what has been earned in total, and the case for
 * not withdrawing.
 *
 * Deliberately narrow — two things, nothing else. Not the Savings page's
 * this-month detail, and not a place a parent settles anything from; both
 * belong on their own screens. Read-only, the same as Savings, and built
 * from the same shapes: the `.total` gradient card for the one figure that
 * matters most, `.figures` for the pair beside the chart.
 *
 * "How money grows if you leave it alone" is the heading on purpose — the
 * counterfactual is a lesson about leaving money in, not a running tally of
 * what withdrawing "cost". Same numbers either way; the framing is the
 * spec's, not a wording choice made here.
 */

import { useEffect, useState } from 'react'
import { loadLifetime, money } from './api'
import type { Lifetime } from './api'
import { Figure } from './components/parent/ThisWeek'
import { LifetimeChart } from './components/LifetimeChart'

export function LifetimeView() {
  const [data, setData] = useState<Lifetime | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    void loadLifetime()
      .then(setData)
      .catch((problem) => setError((problem as Error).message))
  }, [])

  if (error) {
    return (
      <p className="problem" role="alert">
        Cannot reach CoinQuest: {error}
      </p>
    )
  }

  if (!data) return <p className="loading">Loading…</p>

  const hasHistory = data.real.length > 0
  const currentReal = hasHistory ? data.real[data.real.length - 1].balance_pence : 0
  const currentCounterfactual =
    data.counterfactual.length > 0
      ? data.counterfactual[data.counterfactual.length - 1].balance_pence
      : 0

  return (
    <>
      <header className="masthead">
        <h1>Lifetime</h1>
        <p className="dates">Everything ever earned, and how money grows if you leave it alone</p>
      </header>

      <section className="total">
        <p className="total-label">Total earned to date</p>
        <p className="total-amount">{money(data.total_earned_pence)}</p>
      </section>

      <section className="panel">
        <h2>How money grows if you leave it alone</h2>

        {hasHistory ? (
          <>
            <LifetimeChart real={data.real} counterfactual={data.counterfactual} />
            <div className="figures">
              <Figure label="Real, today" value={money(currentReal)} />
              <Figure
                label="If nothing had ever been withdrawn"
                value={money(currentCounterfactual)}
              />
            </div>
          </>
        ) : (
          <p className="nothing">Nothing saved yet to compare.</p>
        )}
      </section>
    </>
  )
}
