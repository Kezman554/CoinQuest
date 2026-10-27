/**
 * Day and night on the wall (DESIGN.md, Modes).
 *
 * The clock decides: night from NIGHT.from until NIGHT.until, Europe/London,
 * set explicitly — the device's zone and its own light/dark setting have no
 * say. A sun/moon button can flip it until the next scheduled switch, and
 * that override lives in the browser only (useMode.ts); nothing reaches the
 * API or the database.
 *
 * Everything here is plain functions with no imports, because the same code
 * runs twice: in the app, and — stringified by vite.config.ts into an inline
 * script in index.html — before first paint, so the wall never shows day and
 * then changes. One calculation, not a copy of it. Each function refers to
 * the others only by name, and the script includes all of them.
 */

/** Night on the wall. Provisional times, kept here and nowhere else. */
export const NIGHT = { from: '19:00', until: '07:00' } as const

export type Night = { readonly from: string; readonly until: string }
export type Mode = 'day' | 'night'
/** A flip of the mode, and the instant (epoch ms) it stops applying. */
export type Override = { mode: Mode; until: number }

/** Where the override is kept, in localStorage. */
export const MODE_KEY = 'coinquest.mode'

/** "19:00" -> 1140. */
export function toMinutes(hhmm: string): number {
  const [hours, minutes] = hhmm.split(':')
  return Number(hours) * 60 + Number(minutes)
}

/** Minutes past midnight on the London wall clock at `now`. */
export function londonMinutes(now: number): number {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Europe/London',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(now))
  const part = (type: string) => Number(parts.find((p) => p.type === type)?.value)
  return part('hour') * 60 + part('minute')
}

/** What the clock alone says at `now`. Night may run past midnight. */
export function clockMode(now: number, night: Night): Mode {
  const at = londonMinutes(now)
  const from = toMinutes(night.from)
  const until = toMinutes(night.until)
  const isNight = from > until ? at >= from || at < until : at >= from && at < until
  return isNight ? 'night' : 'day'
}

/**
 * The mode at `now`: the stored override while it lasts, the clock otherwise.
 * `stored` is the raw localStorage value, or null; anything unreadable or
 * expired is ignored, and the clock decides.
 */
export function modeFor(now: number, night: Night, stored: string | null): Mode {
  if (stored) {
    try {
      const override = JSON.parse(stored)
      if (
        override &&
        (override.mode === 'day' || override.mode === 'night') &&
        typeof override.until === 'number' &&
        now < override.until
      ) {
        return override.mode
      }
    } catch {
      // Unreadable: the clock decides.
    }
  }
  return clockMode(now, night)
}

/**
 * The next instant the clock switches mode after `now` — when an override
 * made now runs out. Counted on the London wall clock, then corrected once
 * if a clock change falls in between (the night spans 01:00, where both
 * changes happen), so 07:00 means 07:00 on the morning the clocks went
 * forward too.
 */
export function nextSwitch(now: number, night: Night): number {
  const target = toMinutes(clockMode(now, night) === 'night' ? night.until : night.from)
  const minute = 60_000
  const startOfMinute = now - (now % minute)
  const ahead = (target - londonMinutes(now) + 1440) % 1440 || 1440
  const at = startOfMinute + ahead * minute
  const drift = ((londonMinutes(at) - target + 720 + 1440) % 1440) - 720
  return at - drift * minute
}
