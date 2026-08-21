/**
 * What the week is on track to pay.
 *
 * "On track" is the honest word and the wording says it: nothing here has been
 * agreed by anybody, and a parent settles the week on Sunday on figures they
 * have read. The breakdown is shown because a single number nobody can account
 * for is exactly the argument this app exists to end.
 *
 * The chore pay is one pot, paid whole or not at all, so it gets a line of its
 * own saying which of the two it currently is. A child who can see that £1.40
 * is at stake and why has something he can act on; a total that quietly went
 * down by £1.40 is just a number that got worse.
 */

import type { Totals } from '../api'
import { money } from '../api'

export function Total({ totals }: { totals: Totals }) {
  return (
    <section className="total">
      <p className="total-label">On track for</p>
      <p className="total-amount">{money(totals.total_pence)}</p>

      <dl className="breakdown">
        <div>
          <dt>Every week</dt>
          <dd>{money(totals.base_pence)}</dd>
        </div>
        <div className={totals.chore_pay_awarded ? '' : 'at-risk'}>
          <dt>Chores</dt>
          <dd>
            {totals.chore_pay_awarded
              ? money(totals.chore_pay_pence)
              : `${money(totals.chore_pay_at_stake_pence)} still to win`}
          </dd>
        </div>
        <div>
          <dt>Bonus</dt>
          <dd>{money(totals.bonus_pence)}</dd>
        </div>
        {totals.reward_pence > 0 && (
          <div>
            <dt>Rewards</dt>
            <dd>{money(totals.reward_pence)}</dd>
          </div>
        )}
      </dl>

      {!totals.chore_pay_awarded && totals.chore_pay_at_stake_pence > 0 && (
        <p className="total-note">
          The chore money is all or nothing. Finish the week and it is yours.
        </p>
      )}
    </section>
  )
}
