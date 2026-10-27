/**
 * What the week is on track to pay.
 *
 * "On track" is the honest word and the wording says it: nothing here has been
 * agreed by anybody, and a parent settles the week on Sunday on figures they
 * have read. The breakdown is shown because a single number nobody can account
 * for is exactly the argument this app exists to end.
 *
 * The headline is the payable total: the settled figure plus any reward a
 * parent entered against the week. Those two are separate in the books for a
 * good reason — a reward never moves with the chore result — but the child is
 * asking what he will be handed, and that is the sum.
 *
 * The chore pay is one pot, paid whole or not at all, so it gets a line of its
 * own saying which of the two it currently is. A child who can see that £1.40
 * is at stake and why has something he can act on; a total that quietly went
 * down by £1.40 is just a number that got worse.
 *
 * A bonus chore held back as a make-good gets a line too. It is already
 * absent from the bonus figure — spent, not paid — and leaving it out
 * entirely would read as though it had simply been ignored rather than
 * worked and given up on purpose.
 *
 * "On track for" is only honest while the week is still open. A closed week
 * paged back to reads its own past tense — "Settled at" or "Voided at" —
 * so a figure that is now permanent does not sound like a projection still
 * moving.
 *
 * The missed-chore notice (Recovery) sits in this card too: what went wrong
 * with this figure, ending with what the make-good route takes it back to.
 * While the notice shows, the separate make-good line does not — it would
 * say the same thing twice.
 *
 * On a settled or voided week the card loses the shine — `settled` rather
 * than gold, a muted coin — and the page drops every shadow (App.css), so
 * nothing on a closed week looks tappable.
 *
 * The make-good line lives here rather than on the day tile that happened to
 * be marked. A route back is a fact about the week, not about Wednesday, and
 * it has to still be readable on Friday by somebody who has just walked past
 * the wall and marked nothing. It sits beside the number it restores because
 * that number is the whole argument for doing it. Deliberately one line: not
 * a panel, not a second screen, and nothing at all when the engine says there
 * is no way back — see makeGoodLine.
 */

import type { MakeGood, RecoveryPanel, Totals } from '../api'
import { money } from '../api'
import { makeGoodLine, recoveryNotice, weekdayOf } from '../words'
import { Coin } from './Coin'
import { Recovery } from './Recovery'

export function Total({
  totals,
  status = 'open',
  makeGood = null,
  recovery = null,
}: {
  totals: Totals
  status?: string
  makeGood?: MakeGood | null
  recovery?: RecoveryPanel | null
}) {
  const label =
    status === 'settled' ? 'Settled at' : status === 'voided' ? 'Voided at' : 'On track for'
  const past = status !== 'open'
  const routeBack = past ? null : makeGood
  const notice =
    recovery && recoveryNotice(recovery, weekdayOf(recovery.deadline)) ? (
      <Recovery recovery={recovery} makeGood={routeBack} />
    ) : null
  // With a notice showing, the make-good clause ends the notice instead.
  const route = notice ? null : makeGoodLine(routeBack)

  return (
    <section className={past ? 'total total-past' : 'total'}>
      <p className="total-label">{label}</p>
      <div className="total-figure">
        <Coin />
        <p className="total-amount">{money(totals.payable_total_pence)}</p>
      </div>

      <dl className="breakdown">
        <div>
          <dt>Every week</dt>
          <dd>{money(totals.base_pence)}</dd>
        </div>
        <div className={totals.chore_pay_awarded ? 'won' : 'at-risk'}>
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
        {totals.reward_pence + totals.ad_hoc_reward_pence > 0 && (
          <div>
            <dt>Rewards</dt>
            <dd>{money(totals.reward_pence + totals.ad_hoc_reward_pence)}</dd>
          </div>
        )}
        {totals.held_as_makegood_pence > 0 && (
          <div>
            <dt>Held as a make-good</dt>
            <dd>{money(totals.held_as_makegood_pence)}</dd>
          </div>
        )}
      </dl>

      {!totals.chore_pay_awarded && totals.chore_pay_at_stake_pence > 0 && (
        <p className="total-note">
          The chore money is all or nothing. Finish the week and it is yours.
        </p>
      )}

      {(notice || route) && (
        <div className="total-route">
          {notice}
          {route && <p className="total-makegood">{route}</p>}
        </div>
      )}
    </section>
  )
}
