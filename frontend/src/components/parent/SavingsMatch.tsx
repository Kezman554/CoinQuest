/**
 * The monthly savings match: what it is on track to pay, and settling it.
 *
 * Same readback-before-commit discipline as ThisWeek's own Settle button:
 * Settle re-fetches the proposal the instant it is pressed and opens the PIN
 * dialog on that fresh figure, never on whatever this panel happened to be
 * showing a moment ago — see `settle`'s own check, which refuses an agreed
 * figure that no longer matches what the month currently proposes.
 *
 * A month can be previewed before it has finished — see `month_has_ended` —
 * and this panel shows that preview plainly rather than hiding the section
 * until there is something to settle: a parent watching the figure climb
 * over the month is exactly what the ladder is for. Settle is only offered
 * once the month is actually over.
 */

import { useState } from 'react'
import { money } from '../../api'
import type { SavingsMatchProposal, SettledMonth } from '../../parentApi'
import { loadSavingsMatchProposal, settleMonth } from '../../parentApi'
import type { PinAct } from './PinDialog'
import { Figure } from './ThisWeek'
import { longDate, monthName } from '../../words'

type Ask = { ask: (act: PinAct) => void }

export function SavingsMatch({
  proposal,
  proposalError,
  settledMonths,
  ask,
}: Ask & {
  proposal: SavingsMatchProposal | null
  proposalError: string | null
  settledMonths: SettledMonth[]
}) {
  const lastSettled = settledMonths.length > 0 ? settledMonths[settledMonths.length - 1] : null

  return (
    <section className="panel">
      <h2>Savings match</h2>

      {lastSettled && (
        <p className="closed-note">
          {monthName(lastSettled.period_start)}: matched {money(lastSettled.match_pence)} at{' '}
          {lastSettled.rate_percent}% on a low of {money(lastSettled.balance_low_pence)}, settled{' '}
          {longDate(lastSettled.settled_at.slice(0, 10))} by {lastSettled.settled_by}.
        </p>
      )}

      {proposal ? (
        <>
          <div className="figures">
            <Figure label="Rate in force" value={`${proposal.rate_percent}%`} />
            <Figure
              label={`${monthName(proposal.period_start)}'s low so far`}
              value={money(proposal.balance_low_pence)}
            />
            <Figure
              label={proposal.month_has_ended ? 'This month pays' : 'Would pay if nothing changes'}
              value={money(proposal.match_pence)}
              big
            />
            {proposal.had_withdrawal && (
              <Figure
                label="Rate reset"
                value="a withdrawal happened this month"
                warn
              />
            )}
          </div>

          {proposal.month_has_ended ? (
            <SettleButton ask={ask} />
          ) : (
            <p className="act-note">
              {monthName(proposal.period_start)} is not over yet — these figures will keep
              moving until it ends, and nothing can be settled before then.
            </p>
          )}
        </>
      ) : (
        <p className="nothing">
          {proposalError ?? 'Nothing has been saved yet for the match to work from.'}
        </p>
      )}
    </section>
  )
}

/** Fetches the true figure the instant it is pressed, and only then opens
 * the PIN dialog — mirrors ThisWeek's SettleButton exactly, for the same
 * reason: what gets agreed to has to be the figure about to be stored, not
 * whatever this panel happened to be showing when it was pressed. Takes no
 * proposal of its own for that reason — there is nothing worth trusting
 * here that a fresh read does not already get again a moment later. */
function SettleButton({ ask }: Ask) {
  const [checking, setChecking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)

  const settle = async () => {
    setChecking(true)
    setProblem(null)
    try {
      const fresh = await loadSavingsMatchProposal()
      if (!fresh.month_has_ended) {
        setProblem(`${monthName(fresh.period_start)} is no longer the month waiting to settle.`)
        return
      }
      ask({
        title: 'Settle the savings match',
        summary: `${monthName(fresh.period_start)} settles at ${money(fresh.match_pence)}.`,
        lines: [
          `${fresh.rate_percent}% on a low of ${money(fresh.balance_low_pence)}${
            fresh.cap_pence < fresh.balance_low_pence
              ? `, capped at ${money(fresh.cap_pence)}`
              : ''
          }.`,
          fresh.had_withdrawal
            ? 'A withdrawal happened this month, which reset the rate and changed what the low is measured from.'
            : `${fresh.clean_months_in_a_row} clean ${
                fresh.clean_months_in_a_row === 1 ? 'month' : 'months'
              } in a row produced this rate.`,
        ],
        confirmLabel: `Settle at ${money(fresh.match_pence)}`,
        permanent: true,
        run: (pin) => settleMonth(pin, fresh.match_pence).then(() => undefined),
      })
    } catch (error) {
      setProblem((error as Error).message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="settle-button">
      <button type="button" className="button button-do" onClick={() => void settle()} disabled={checking}>
        {checking ? 'Working out the true figure…' : 'Settle the match'}
      </button>
      {problem && (
        <p className="dialog-error" role="alert">
          {problem}
        </p>
      )}
    </div>
  )
}
