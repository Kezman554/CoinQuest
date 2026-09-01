/**
 * Oliver's savings page.
 *
 * Read-only, the same as the rest of his week — nothing here is a control,
 * because saving is not a task with a tick box. It answers four questions in
 * the order he'd ask them: how much is there, what is it earning, what will
 * next month add if nothing changes, and how close is that to the point
 * where saving more stops earning more.
 *
 * Built from the same two shapes "This week" already uses — the gradient
 * `.total` card for the one figure that matters most, and a `.figures` grid
 * for the rest — rather than inventing a second visual language for a second
 * screen. `Figure` itself is imported from the parent view's ThisWeek: it is
 * a plain, presentational atom with nothing PIN-shaped about it, the same
 * way PinDialog already crosses that boundary the other way in App.tsx.
 */

import { useCallback, useEffect, useState } from 'react'
import {
  loadDepositors,
  loadMyPendingDeposits,
  loadSavingsBalance,
  loadSavingsMatchProposal,
  money,
  parsePence,
  submitDeposit,
} from './api'
import type { DepositRequest, Depositors, SavingsBalance, SavingsMatchProposal } from './api'
import { Figure } from './components/parent/ThisWeek'
import { monthName, shortDate } from './words'

export function SavingsView() {
  const [balance, setBalance] = useState<SavingsBalance | null>(null)
  const [proposal, setProposal] = useState<SavingsMatchProposal | null>(null)
  const [proposalNote, setProposalNote] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [depositors, setDepositors] = useState<Depositors | null>(null)
  const [pending, setPending] = useState<DepositRequest[]>([])

  const refresh = useCallback(async () => {
    try {
      setBalance(await loadSavingsBalance())
    } catch (problem) {
      setError((problem as Error).message)
      return
    }
    try {
      setProposal(await loadSavingsMatchProposal())
    } catch {
      // No savings entries at all yet — nothing to project. The balance
      // above already says the account is empty; this is not an error.
      setProposalNote('Nothing saved yet for the match to work from.')
    }
    const who = await loadDepositors()
    setDepositors(who)
    setPending(await loadMyPendingDeposits(who.child_name))
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  if (error) {
    return (
      <p className="problem" role="alert">
        Cannot reach CoinQuest: {error}
      </p>
    )
  }

  if (!balance) return <p className="loading">Loading your savings…</p>

  return (
    <>
      <header className="masthead">
        <h1>Savings</h1>
        <p className="dates">What&rsquo;s put away, and what it&rsquo;s earning</p>
      </header>

      <section className="total">
        <p className="total-label">In the account</p>
        <p className="total-amount">{money(balance.balance_pence)}</p>
      </section>

      {proposal ? (
        <section className="panel">
          <h2>The monthly match</h2>

          <div className="figures">
            <Figure label="Current rate" value={`${proposal.rate_percent}%`} big />
            <Figure
              label="Clean months in a row"
              value={String(proposal.clean_months_in_a_row)}
              note={
                proposal.had_withdrawal
                  ? 'A withdrawal this month reset it'
                  : undefined
              }
              warn={proposal.had_withdrawal}
            />
            <Figure
              label={
                proposal.month_has_ended
                  ? `What ${monthName(proposal.period_start)} pays`
                  : 'If nothing changes, this month pays'
              }
              value={money(proposal.match_pence)}
            />
            <Figure
              label={`${monthName(proposal.period_start)}'s low so far`}
              value={money(proposal.balance_low_pence)}
            />
          </div>

          <CapProgress lowPence={proposal.balance_low_pence} capPence={proposal.cap_pence} />
        </section>
      ) : (
        <section className="panel">
          <p className="nothing">{proposalNote}</p>
        </section>
      )}

      {depositors && (
        <DepositForm
          childName={depositors.child_name}
          pending={pending}
          onSubmitted={refresh}
        />
      )}
    </>
  )
}

/**
 * Propose a deposit — birthday money, a gift, anything that did not come
 * through payday. No PIN: it waits for a parent the same way a claim does,
 * and the balance above does not move until one confirms it.
 */
function DepositForm({
  childName,
  pending,
  onSubmitted,
}: {
  childName: string
  pending: DepositRequest[]
  onSubmitted: () => void
}) {
  const [amount, setAmount] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const pence = parsePence(amount)
  const ready = pence !== null && pence > 0 && note.trim().length > 0

  const submit = async () => {
    if (!ready) return
    setBusy(true)
    setError(null)
    try {
      await submitDeposit(pence, note.trim(), childName)
      setAmount('')
      setNote('')
      await onSubmitted()
    } catch (problem) {
      setError((problem as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Add money you got another way</h2>
      <p className="act-note">
        Birthday money, a gift — anything that did not come from your weekly
        pay. It waits for a parent to say yes before it counts.
      </p>

      <div className="act-row">
        <input
          type="text"
          inputMode="decimal"
          placeholder="Amount, e.g. £5"
          value={amount}
          onChange={(event) => setAmount(event.target.value)}
        />
        <input
          type="text"
          placeholder="Where it came from"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
        <button type="button" className="button" disabled={!ready || busy} onClick={submit}>
          {busy ? 'Sending…' : 'Add it'}
        </button>
      </div>

      {error && (
        <p className="problem" role="alert">
          {error}
        </p>
      )}

      {pending.length > 0 && (
        <ul className="deposit-pending">
          {pending.map((request) => (
            <li key={request.id}>
              <span>
                {money(request.amount_pence)} — {request.note}
              </span>
              <span className="deposit-pending-note">
                Waiting for a parent, added {shortDate(request.occurred_on)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** How much of the £100 (or whatever the scheme's cap is) is already
 * earning the match. Past the cap the bar stays full rather than reading
 * as though saving more had stopped counting — it hasn't, it just stops
 * raising the match, which the figures above already say plainly. */
function CapProgress({ lowPence, capPence }: { lowPence: number; capPence: number }) {
  const filled = capPence > 0 ? Math.min(lowPence / capPence, 1) : 1
  const reached = lowPence >= capPence

  return (
    <div className="savings-cap">
      <div className="savings-cap-bar">
        <div className="savings-cap-fill" style={{ width: `${filled * 100}%` }} />
      </div>
      <p className="savings-cap-note">
        {reached
          ? `The full ${money(capPence)} is earning the match already.`
          : `${money(lowPence)} of ${money(capPence)} toward the cap.`}
      </p>
    </div>
  )
}
