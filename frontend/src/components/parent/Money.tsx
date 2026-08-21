/**
 * The three money acts that are not settling: rewards, payday, and savings.
 *
 * Settling and paying are separate, days apart in practice, and separately
 * authorised. A settled week reads as owed until somebody hands the money
 * over — otherwise "did we actually pay him for that week?" is answerable only
 * from memory, which is the problem this app exists to solve.
 */

import { useState } from 'react'
import { money, parsePence } from '../../api'
import type { Owed, Preset, Savings } from '../../parentApi'
import {
  payWeeks,
  reconcile,
  recordOpeningBalance,
  recordPreset,
  recordReward,
  recordWithdrawal,
} from '../../parentApi'
import type { Reconciliation } from '../../parentApi'
import type { PinAct } from './PinDialog'
import { shortDate } from '../../words'
import { plural } from '../../words'

type Ask = { ask: (act: PinAct) => void }

// --- Rewards ---------------------------------------------------------------

export function Rewards({ presets, ask }: Ask & { presets: Preset[] }) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const pence = parsePence(amount)
  const ready = pence !== null && pence > 0 && reason.trim().length > 0

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
          className="button"
          disabled={!ready}
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
            className="button button-quiet"
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

      {weeks.length > 0 && (
        <div className="act-row">
          <p className="batch-action">
            {money(total)} across {weeks.length}{' '}
            {plural(weeks.length, 'week', 'weeks')}
          </p>
          <input
            type="text"
            inputMode="decimal"
            placeholder="Banked, e.g. £3"
            value={deposit}
            onChange={(event) => setDeposit(event.target.value)}
          />
          <button
            type="button"
            className="button button-do"
            disabled={!ready}
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
      )}
      {deposited > total && (
        <p className="dialog-error">
          {money(deposited)} cannot come out of a payment of {money(total)}.
        </p>
      )}
    </section>
  )
}

// --- Savings ---------------------------------------------------------------

export function SavingsPanel({ savings, ask }: Ask & { savings: Savings }) {
  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [actual, setActual] = useState('')
  const [checked, setChecked] = useState<Reconciliation | null>(null)
  const [opening, setOpening] = useState('')

  const pence = parsePence(amount)
  const ready = pence !== null && pence > 0 && reason.trim().length > 0
  const openingPence = parsePence(opening)
  const empty = savings.entries.length === 0

  return (
    <section className="panel">
      <h2>Savings — {money(savings.balance_pence)}</h2>

      {empty ? (
        <div className="act">
          <h3>Opening balance</h3>
          <p className="act-note">
            What was already in the account when this started. Recorded once,
            and it has to be first: everything after it is a movement from a
            balance.
          </p>
          <div className="act-row">
            <input
              type="text"
              inputMode="decimal"
              placeholder="e.g. £12.40"
              value={opening}
              onChange={(event) => setOpening(event.target.value)}
            />
            <button
              type="button"
              className="button"
              disabled={openingPence === null}
              onClick={() =>
                openingPence !== null &&
                ask({
                  title: 'Record the opening balance',
                  summary: `${money(openingPence)} was already in the account.`,
                  lines: ['This can only be done once.'],
                  confirmLabel: 'Record it',
                  permanent: true,
                  run: (pin) =>
                    recordOpeningBalance(pin, openingPence).then(() => {
                      setOpening('')
                    }),
                })
              }
            >
              Record
            </button>
          </div>
        </div>
      ) : (
        <>
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
                onChange={(event) => setAmount(event.target.value)}
              />
              <input
                type="text"
                placeholder="What it went on"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
              <button
                type="button"
                className="button"
                disabled={!ready}
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
                onChange={(event) => setActual(event.target.value)}
              />
              <button
                type="button"
                className="button"
                disabled={parsePence(actual) === null}
                onClick={async () => {
                  const value = parsePence(actual)
                  if (value === null) return
                  setChecked(await reconcile(value))
                }}
              >
                Check
              </button>
            </div>
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
        </>
      )}

      {savings.entries.length > 0 && (
        <table className="ledger">
          <tbody>
            {[...savings.entries].reverse().map((entry) => (
              <tr key={entry.id}>
                <td>{shortDate(entry.occurred_on)}</td>
                <td>{entry.reason ?? entry.entry_type}</td>
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
