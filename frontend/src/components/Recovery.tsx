/**
 * What has been ruled missed, and what can still be done about it.
 *
 * It sits inside the money card, beside the make-good line, because both are
 * about the figure in that card: what went wrong with it, and how to get it
 * back. It used to take a full-width row above the week, which on the
 * 1280x800 panel was height the days needed. It is still the only thing on
 * the screen that is time-limited, so on the last day it takes the danger
 * edge and an alarm clock — the icon is decoration on top of words that say
 * it in full ("Today is the last day…"), never a substitute for them.
 *
 * It disappears entirely when nothing is outstanding — a standing empty box
 * teaches the eye to skip the place the warning will appear in.
 */

import type { RecoveryPanel } from '../api'
import { recoveryNotice, weekdayOf } from '../words'

export function Recovery({ recovery }: { recovery: RecoveryPanel }) {
  const notice = recoveryNotice(recovery, weekdayOf(recovery.deadline))
  if (!notice) return null

  return (
    <section className={`notice notice-${notice.tone}`} role="status">
      <h2>
        {notice.tone === 'urgent' && <AlarmClock />}
        {notice.headline}
      </h2>
      <p>{notice.detail}</p>
    </section>
  )
}

/** Our own alarm clock, stroked in the notice's own text colour. */
function AlarmClock() {
  return (
    <svg className="alarm-clock" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="13" r="7.5" />
      <path d="M12 9v4.5l3 2M4.5 4.5 2 7M19.5 4.5 22 7M7 20l-1.5 2M17 20l1.5 2" />
    </svg>
  )
}
