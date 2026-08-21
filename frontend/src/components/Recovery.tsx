/**
 * What has been ruled missed, and what can still be done about it.
 *
 * It sits at the top of the page because it is the only thing on the screen
 * that is time-limited: everything else can be read at leisure, and this
 * cannot. It disappears entirely when nothing is outstanding — a standing
 * empty box teaches the eye to skip the place the warning will appear in.
 */

import type { RecoveryPanel } from '../api'
import { recoveryNotice, weekdayOf } from '../words'

export function Recovery({ recovery }: { recovery: RecoveryPanel }) {
  const notice = recoveryNotice(recovery, weekdayOf(recovery.deadline))
  if (!notice) return null

  return (
    <section className={`notice notice-${notice.tone}`} role="status">
      <h2>{notice.headline}</h2>
      <p>{notice.detail}</p>
    </section>
  )
}
