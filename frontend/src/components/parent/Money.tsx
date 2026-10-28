/**
 * The three money acts that are not settling: rewards, payday, and savings.
 *
 * Settling and paying are separate, days apart in practice, and separately
 * authorised. A settled week reads as owed until somebody hands the money
 * over — otherwise "did we actually pay him for that week?" is answerable only
 * from memory, which is the problem this app exists to solve.
 */

import { byWhom } from '../../parentWords'
import { useId, useState } from 'react'
import { money, parsePence } from '../../api'
import type { DepositRequest, Depositors, Owed, Preset, Savings } from '../../parentApi'
import {
  confirmDeposit,
  payWeeks,
  reconcile,
  recordParentDeposit,
  recordPreset,
  recordReward,
  recordWithdrawal,
  rejectDeposit,
} from '../../parentApi'
import type { Reconciliation } from '../../parentApi'
import type { PinAct } from './PinDialog'
import { shortDate } from '../../words'
import { plural } from '../../words'
import { Why } from '../Why'

type Ask = { ask: (act: PinAct) => void }

// --- Rewards ---------------------------------------------------------------

export function Rewards({ presets, ask }: Ask & { presets: Preset[] }) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const pence = parsePence(amount)
  const ready = pence !== null && pence > 0 && reason.trim().length > 0
  const whyId = useId()
  const why = ready ? null : 'Needs an amount and what it is for.'

  return (
    <section className="panel">
      <h2>Record a reward</h2>
      <p className="act-note">
        A reward pays its own amount and belongs to the week it was entered in.
        It never touches that week&rsquo;s settled figures — a bad week at the
        hoover does not make an award smaller, and voiding a week does not take
        it back.
      </p>

      <div className="act-row">
        <input
          type="text"
          inputMode="decimal"
          placeholder="Amount, e.g. £2.50"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
        <input
          type="text"
          placeholder="What it is for"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <button
          type="button"
          className="button button-confirm"
          disabled={!ready}
          aria-describedby={why ? whyId : undefined}
          onClick={() =>
            ready &&
            ask({
              title: 'Record a reward',
              summary: `${money(pence)} — ${reason.trim()}`,
              confirmLabel: `Record ${money(pence)}`,
              run: (pin) =>
                recordReward(pin, amount, reason).then(() => {
                  setAmount('')
                  setReason('')
                }),
            })
          }
        >
          Record
        </button>
      </div>
      <Why id={whyId} reason={why} />

      {amount !== '' && pence === null && (
        <p className="dialog-error">
          That is not an amount that can be paid in coins.
        </p>
      )}

      <div className="presets">
        {presets.map((preset) => (
          <button
            key={preset.key}
            type="button"
            className="button button-confirm"
            onClick={() =>
              ask({
                title: preset.name,
                summary: `${preset.amount} — the amount is the scheme's, not a starting point.`,
                confirmLabel: `Record ${preset.amount}`,
                run: (pin) => recordPreset(pin, preset.key).then(() => undefined),
              })
            }
          >
            {preset.name} {preset.amount}
          </button>
        ))}
      </div>
    </section>
  )
}

// --- Payday ----------------------------------------------------------------

export function Payday({ owed, ask }: Ask & { owed: Owed[] }) {
  const [chosen, setChosen] = useState<number[]>([])
  const [deposit, setDeposit] = useState('')
  const whyId = useId()

  if (owed.length === 0) {
    return (
      <section className="panel">
        <h2>Owed</h2>
        <p className="nothing">Nothing is waiting to be paid.</p>
      </section>
    )
  }

  const weeks = owed.filter((week) => chosen.includes(week.week_id))
  const total = weeks.reduce((sum, week) => sum + week.owed_pence, 0)
  const deposited = parsePence(deposit) ?? 0
  const ready = weeks.length > 0 && deposited <= total
  const overpaid = deposited > total

  return (
    <section className="panel">
      <h2>Owed</h2>
      <p className="act-note">
        Settled, and not yet handed over. What he keeps is his and is recorded
        nowhere; only what goes into the account is.
      </p>

      <ul className="owed">
        {owed.map((week) => (
          <li key={week.week_id}>
            <label>
              <input
                type="checkbox"
                checked={chosen.includes(week.week_id)}
                onChange={(event) =>
                  setChosen((current) =>
                    event.target.checked
                      ? [...current, week.week_id]
                      : current.filter((id) => id !== week.week_id),
                  )
                }
              />
              <span className="owed-week">
                {shortDate(week.start_date)} – {shortDate(week.end_date)}
              </span>
              <span className="owed-amount">{money(week.owed_pence)}</span>
              {week.reward_pence > 0 && (
                <span className="owed-note">
                  includes {money(week.reward_pence)} of rewards
                </span>
              )}
            </label>
          </li>
        ))}
      </ul>

      {/* Mark paid stays in place before any week is ticked, disabled and
          saying so, rather than appearing only once one is. */}
      <div className="act-row">
        {weeks.length > 0 && (
          <p className="batch-action">
            {money(total)} across {weeks.length}{' '}
            {plural(weeks.length, 'week', 'weeks')}
          </p>
        )}
        <input
          type="text"
          inputMode="decimal"
          placeholder="Banked, e.g. £3"
          value={deposit}
          disabled={weeks.length === 0}
          onChange={(event) => setDeposit(event.target.value)}
        />
        <button
          type="button"
          className="button button-confirm"
          disabled={!ready}
          aria-describedby={ready ? undefined : whyId}
          onClick={() =>
            ready &&
            ask({
              title: 'Mark paid',
              summary: `${money(total)} handed over.`,
              lines: [
                `${money(deposited)} into the account, ${money(
                  total - deposited,
                )} kept.`,
                'The deposit is split across the weeks in date order, so each week records its share.',
              ],
              confirmLabel: 'Mark paid',
              permanent: true,
              run: (pin) =>
                payWeeks(
                  pin,
                  weeks.map((week) => week.week_id),
                  deposited,
                ).then(() => {
                  setChosen([])
                  setDeposit('')
                }),
            })
          }
        >
          Mark paid
        </button>
      </div>
      {overpaid ? (
        <Why
          id={whyId}
          className="dialog-error"
          reason={`${money(deposited)} cannot come out of a payment of ${money(total)}.`}
        />
      ) : (
        <Why id={whyId} reason={weeks.length === 0 ? 'Tick the weeks being paid first.' : null} />
      )}
    </section>
  )
}

// --- Savings ---------------------------------------------------------------

export function SavingsPanel({
  savings,
  depositors,
  pendingDeposits,
  ask,
}: Ask & {
  savings: Savings
  depositors: Depositors | null
  pendingDeposits: DepositRequest[]
}) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [actual, setActual] = useState('')
  const [checked, setChecked] = useState<Reconciliation | null>(null)

  const pence = parsePence(amount)
  const ready = pence !== null && pence > 0 && reason.trim().length > 0
  const empty = savings.entries.length === 0
  const logWhy = useId()
  const checkWhy = useId()
  const logReason = empty
    ? 'Nothing in the account to withdraw.'
    : ready
      ? null
      : 'Needs an amount and what it went on.'
  const checkReason = empty
    ? 'Nothing in the account to check yet.'
    : parsePence(actual) === null
      ? 'Needs what the account really holds.'
      : null

  return (
    <section className="panel">
      <h2>Savings — {money(savings.balance_pence)}</h2>

      {depositors && <DepositAct depositors={depositors} ask={ask} />}

      {pendingDeposits.length > 0 && (
        <PendingDeposits requests={pendingDeposits} ask={ask} />
      )}

      {/* Withdrawing and reconciling stay on screen while the account is
          empty, disabled and saying why (DESIGN.md: a control the state
          forbids keeps its place). Depositing, above (with a note like
          "opening balance" for the very first one), is the only way money
          gets in. */}
      <div className="act">
        <h3>Log a withdrawal</h3>
        <p className="act-note">
          His own money leaving his own account. Nothing is ever deducted
          from what he earned — this is not that.
        </p>
        <div className="act-row">
          <input
            type="text"
            inputMode="decimal"
            placeholder="Amount"
            value={amount}
            disabled={empty}
            onChange={(event) => setAmount(event.target.value)}
          />
          <input
            type="text"
            placeholder="What it went on"
            value={reason}
            disabled={empty}
            onChange={(event) => setReason(event.target.value)}
          />
          <button
            type="button"
            className="button button-danger"
            disabled={logReason !== null}
            aria-describedby={logReason ? logWhy : undefined}
            onClick={() =>
              ready &&
              ask({
                title: 'Log a withdrawal',
                summary: `${money(pence)} out — ${reason.trim()}`,
                lines: [
                  `The balance goes to ${money(
                    savings.balance_pence - pence,
                  )}.`,
                ],
                confirmLabel: 'Log it',
                danger: true,
                run: (pin) =>
                  recordWithdrawal(pin, pence, reason).then(() => {
                    setAmount('')
                    setReason('')
                  }),
              })
            }
          >
            Log
          </button>
        </div>
        <Why id={logWhy} reason={logReason} />
      </div>

      <div className="act">
        <h3>Reconcile</h3>
        <p className="act-note">
          Compare the ledger with what the account really holds. This
          records nothing: a difference means something happened that
          nobody wrote down, and papering over it would destroy the only
          information the difference carries.
        </p>
        <div className="act-row">
          <input
            type="text"
            inputMode="decimal"
            placeholder="What the account really holds"
            value={actual}
            disabled={empty}
            onChange={(event) => setActual(event.target.value)}
          />
          <button
            type="button"
            className="button"
            disabled={checkReason !== null}
            aria-describedby={checkReason ? checkWhy : undefined}
            onClick={async () => {
              const value = parsePence(actual)
              if (value === null) return
              setChecked(await reconcile(value))
            }}
          >
            Check
          </button>
        </div>
        <Why id={checkWhy} reason={checkReason} />
        {checked && (
          <p className={checked.agrees ? 'reconciled-ok' : 'reconciled-off'}>
            {checked.agrees
              ? `They agree: ${money(checked.recorded_balance_pence)}.`
              : `The ledger says ${money(
                  checked.recorded_balance_pence,
                )}, the account holds ${money(
                  checked.actual_balance_pence,
                )}. ${checked.put_right_by}`}
          </p>
        )}
      </div>

      {savings.entries.length > 0 && (
        <table className="ledger">
          <tbody>
            {[...savings.entries].reverse().map((entry) => (
              <tr key={entry.id}>
                <td>{shortDate(entry.occurred_on)}</td>
                <td>
                  {entry.reason ?? entry.entry_type}
                  {entry.posted_by && (
                    <span className="ledger-posted-by"> — {byWhom(entry.posted_by)}</span>
                  )}
                </td>
                <td className="ledger-amount">
                  {entry.amount_pence < 0 ? '−' : '+'}
                  {money(Math.abs(entry.amount_pence))}
                </td>
                <td className="ledger-balance">{money(entry.balance_after_pence)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

/**
 * A parent posting a deposit directly — birthday money, a gift, or the
 * opening balance at go-live, entered here with a note like "opening
 * balance" rather than through the dedicated one-off endpoint. Authorised
 * the moment it is submitted: there is no pending step, because the PIN
 * already proves the party.
 */
function DepositAct({ depositors, ask }: Ask & { depositors: Depositors }) {
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')

  const pence = parsePence(amount)
  const ready = pence !== null && pence > 0 && note.trim().length > 0
  const whyId = useId()
  const why = ready ? null : 'Needs an amount and where it came from.'

  return (
    <div className="act">
      <h3>Record a deposit</h3>
      <p className="act-note">
        Money that did not come from payday — a gift, birthday money, or the
        opening balance at the very start. Lands in the account straight
        away, recorded as posted by whoever's PIN agrees it
        {depositors.parent_names.length > 1 ? ` (${depositors.parent_names.join(' or ')})` : ''}.
      </p>
      <div className="act-row">
        <input
          type="text"
          inputMode="decimal"
          placeholder="Amount, e.g. £10"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
        <input
          type="text"
          placeholder="Where it came from"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <button
          type="button"
          className="button button-confirm"
          disabled={!ready}
          aria-describedby={why ? whyId : undefined}
          onClick={() =>
            ready &&
            ask({
              title: 'Record a deposit',
              summary: `${money(pence)} — ${note.trim()}`,
              confirmLabel: `Record ${money(pence)}`,
              run: (pin) =>
                recordParentDeposit(pin, pence, note.trim()).then(() => {
                  setAmount('')
                  setNote('')
                }),
            })
          }
        >
          Record
        </button>
      </div>
      <Why id={whyId} reason={why} />
    </div>
  )
}

/** What the child has proposed, waiting on a parent — the same wait a claimed
 * chore sits in, and the same asymmetry: confirming carries the PIN because
 * it hands money over, and so, here, does declining, if only because both
 * are the one credential this queue has. */
function PendingDeposits({ requests, ask }: Ask & { requests: DepositRequest[] }) {
  return (
    <div className="act">
      <h3>From {requests[0].posted_by}, waiting</h3>
      <ul className="deposit-pending">
        {requests.map((request) => (
          <li key={request.id}>
            <span>
              {money(request.amount_pence)} — {request.note}
              <span className="deposit-pending-note">
                {' '}
                added {shortDate(request.occurred_on)}
              </span>
            </span>
            <span className="act-row">
              <button
                type="button"
                className="button button-confirm"
                onClick={() =>
                  ask({
                    title: 'Confirm this deposit',
                    summary: `${money(request.amount_pence)} — ${request.note}`,
                    confirmLabel: 'Confirm',
                    run: (pin) => confirmDeposit(pin, request.id).then(() => undefined),
                  })
                }
              >
                Confirm
              </button>
              <button
                type="button"
                className="button button-danger"
                onClick={() =>
                  ask({
                    title: 'Decline this deposit',
                    summary: `${money(request.amount_pence)} — ${request.note}`,
                    lines: ['It never reaches the ledger; nothing is recorded.'],
                    confirmLabel: 'Decline',
                    danger: true,
                    run: (pin) => rejectDeposit(pin, request.id).then(() => undefined),
                  })
                }
              >
                Decline
              </button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
