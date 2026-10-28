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
 * over the month is exactly what the ladder is for. Settle is there all
 * month, disabled and saying why until the month is actually over.
 *
 * Nothing settles itself, so a month that has ended and would pay something
 * is listed as ready to settle — the same list the wall shows as "Interest
 * for …, going into your bank" until a parent does. Months settle strictly
 * in order, so only the earliest can be settled now. The match is real money
 * paid into his bank account by the parent who holds it (BANK_HOLDER),
 * outside this app; settling records that it was, so it comes after the
 * transfer — and only that parent's PIN can do it (app.routers.savings_match). The bank balance after it is
 * asked for every time, optionally, and checked against the books with the
 * same reconcile action the Savings panel uses — which records nothing.
 */

import { useId, useState } from 'react'
import type { DueMonth } from '../../api'
import { money, parsePence } from '../../api'
import type { Reconciliation, SavingsMatchProposal, SettledMonth } from '../../parentApi'
import { loadSavingsMatchProposal, settleMonth } from '../../parentApi'
import { byWhom } from '../../parentWords'
import type { PinAct } from './PinDialog'
import { Figure } from './ThisWeek'
import { longDate, monthName, monthOnly } from '../../words'
import { Why } from '../Why'

type Ask = { ask: (act: PinAct) => void }

export function SavingsMatch({
  proposal,
  proposalError,
  settledMonths,
  dueMonths,
  ask,
}: Ask & {
  proposal: SavingsMatchProposal | null
  proposalError: string | null
  settledMonths: SettledMonth[]
  dueMonths: DueMonth[]
}) {
  const lastSettled = settledMonths.length > 0 ? settledMonths[settledMonths.length - 1] : null
  // Held here rather than in the button: settling can end this month's turn
  // and unmount the button, and the result is worth reading afterwards.
  const [checked, setChecked] = useState<Reconciliation | null>(null)
  const [checkProblem, setCheckProblem] = useState<string | null>(null)

  return (
    <section className="panel">
      <h2>Savings match</h2>

      {lastSettled && (
        <p className="closed-note">
          {monthName(lastSettled.period_start)}: matched {money(lastSettled.match_pence)} at{' '}
          {lastSettled.rate_percent}% on a low of {money(lastSettled.balance_low_pence)}, settled{' '}
          {longDate(lastSettled.settled_at.slice(0, 10))} by {byWhom(lastSettled.settled_by)}.
        </p>
      )}

      {dueMonths.length > 0 && (
        <div className="act">
          <h3>Ready to settle</h3>
          <ul className="owed match-due">
            {dueMonths.map((month, index) => (
              <li key={month.period_start}>
                <span className="owed-week">{monthName(month.period_start)}</span>{' '}
                <span className="owed-amount">{money(month.match_pence)}</span>{' '}
                <span className="owed-note">
                  {/* Months settle in order: only the one the panel below
                      proposes can be settled now. */}
                  {index === 0 && proposal?.period_start === month.period_start
                    ? 'settle this one now, below'
                    : 'settles once the months before it are settled'}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {proposal ? (
        <>
          <div className="figures">
            <Figure label="Rate in force" value={`${proposal.rate_percent}%`} />
            <Figure
              label={
                proposal.month_has_ended
                  ? `${monthOnly(proposal.period_start)}'s low`
                  : `${monthName(proposal.period_start)}'s low so far`
              }
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

          <SettleButton
            ask={ask}
            blocked={
              proposal.month_has_ended
                ? null
                : `${monthName(proposal.period_start)} is not over yet — these figures will keep moving until it ends, and nothing can be settled before then.`
            }
            onChecked={(result, problem) => {
              setChecked(result)
              setCheckProblem(problem)
            }}
          />
        </>
      ) : (
        <p className="nothing">
          {proposalError ?? 'Nothing has been saved yet for the match to work from.'}
        </p>
      )}

      {checked && (
        <p className={checked.agrees ? 'reconciled-ok' : 'reconciled-off'}>
          {checked.agrees
            ? `The bank and the books agree: ${money(checked.recorded_balance_pence)}.`
            : `The books say ${money(checked.recorded_balance_pence)}, the bank holds ${money(
                checked.actual_balance_pence,
              )}. ${checked.put_right_by}`}
        </p>
      )}
      {checkProblem && (
        <p className="dialog-error" role="alert">
          Settled, but the bank balance could not be checked: {checkProblem}
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
 * here that a fresh read does not already get again a moment later.
 *
 * Beside it, always, the bank balance after the transfer: optional, and
 * checked only once the month has settled, so the books it is compared with
 * already hold the match.
 *
 * Before the month ends it is still here, disabled, with `blocked` as the
 * reason — a control the state forbids keeps its place (DESIGN.md). */
function SettleButton({
  ask,
  blocked,
  onChecked,
}: Ask & {
  blocked: string | null
  onChecked: (result: Reconciliation | null, problem: string | null) => void
}) {
  const whyId = useId()
  const [checking, setChecking] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [bank, setBank] = useState('')

  const settle = async () => {
    setProblem(null)
    const bankPence = bank.trim() ? parsePence(bank) : null
    if (bank.trim() && bankPence === null) {
      setProblem('The bank balance is not an amount. Leave it empty to settle without it.')
      return
    }
    setChecking(true)
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
          'Only once the money has been paid into his bank account.',
          bankPence === null
            ? 'No bank balance given, so nothing will be checked against the books.'
            : `Afterwards, the bank's ${money(bankPence)} is checked against the books.`,
        ],
        confirmLabel: `Settle at ${money(fresh.match_pence)}`,
        permanent: true,
        // The bank balance travels with the settle, so the server holds it
        // to the same rule: only the bank holder's PIN settles the interest,
        // and any other parent is refused with the reason, in this dialog.
        run: async (pin) => {
          const settled = await settleMonth(pin, fresh.match_pence, bankPence)
          onChecked(settled.reconciliation, null)
        },
      })
    } catch (error) {
      setProblem((error as Error).message)
    } finally {
      setChecking(false)
    }
  }

  return (
    <div className="settle-button">
      <p className="act-note">
        Settle it after the money has been paid into his bank account — settling
        records that it was.
      </p>
      <label className="match-bank">
        <span>Bank balance after the transfer (optional)</span>
        <input
          type="text"
          inputMode="decimal"
          placeholder="What the bank account now holds"
          value={bank}
          disabled={blocked !== null}
          onChange={(event) => setBank(event.target.value)}
        />
      </label>
      {/* Raised with the control edge, not gold: settling confirms, and gold
          is money and the child's own do-it actions (DESIGN.md). */}
      <button
        type="button"
        className="button button-confirm"
        onClick={() => void settle()}
        disabled={checking || blocked !== null}
        aria-describedby={blocked ? whyId : undefined}
      >
        {checking ? 'Working out the true figure…' : 'Settle the match'}
      </button>
      <Why id={whyId} reason={blocked} />
      {problem && (
        <p className="dialog-error" role="alert">
          {problem}
        </p>
      )}
    </div>
  )
}
