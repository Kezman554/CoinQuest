/**
 * Oliver's lifetime page: what has been earned in total, where the savings
 * actually came from, and the case for not withdrawing.
 *
 * Deliberately narrow — three things, nothing else. Not the Savings page's
 * this-month detail, and not a place a parent settles anything from; both
 * belong on their own screens. Read-only, the same as Savings, and built
 * from the same shapes: the `.total` gradient card for the one figure that
 * matters most, `.figures` for the rest.
 *
 * The breakdown is deliberately not folded into the total-earned card above
 * it, and does not sum to that figure — it answers a different question
 * (why what's in the account is there, not everything ever earned) and
 * mixing the two would read as though the three parts added up to the
 * headline number. See app.services.lifetime.SavingsBreakdown.
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
        <h2>Where the savings came from</h2>
        <p className="act-note">
          Some of it was never earned at all — the account pays just for
          being left alone, not only for what goes into it.
        </p>
        <div className="figures">
          <Figure label="From payday" value={money(data.savings_breakdown.from_payday_pence)} />
          <Figure
            label="Gifts and extras"
            value={money(data.savings_breakdown.from_gifts_pence)}
          />
          <Figure
            label="Earned from the match alone"
            value={money(data.savings_breakdown.from_match_pence)}
          />
        </div>
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
