/**
 * Is this the kitchen wall? (Session AS; docs/wall-inputs.md)
 *
 * The wall is a 10" touch panel on the hub Pi, running Chromium in kiosk
 * mode with no keyboard of any kind. It shows the hub dashboard at
 * http://localhost:8500, and the dashboard shows CoinQuest in an iframe. So
 * the one thing true of the wall and of nothing else in the house is that
 * CoinQuest is framed by a page on the loopback address: only a browser
 * running on the hub itself can have a localhost parent. A phone or the
 * laptop opening the dashboard reaches it by the hub's LAN address, and
 * opening CoinQuest directly is not framed at all.
 *
 * Why not the obvious signals:
 *  - `(pointer: coarse)` / `(hover: none)`: phones match too, and the wall's
 *    touch controller also registers as a mouse ("ILITEK-TP Mouse" in the
 *    Pi's input devices), so Chromium may report a fine pointer there.
 *  - The user agent: one Linux Chromium looks like any other.
 *  - Screen size: 1280×800 is also a laptop window.
 *
 * `?wall=on` / `?wall=off` overrides the detection on one device and is
 * remembered there; `?wall=auto` forgets it. That is for a kiosk ever opened
 * some other way, and for trying the wall's controls on a laptop.
 *
 * Decided once, when the bundle loads: the answer cannot change while a page
 * is open, and a value that never changes keeps every component simple.
 */

const STORAGE_KEY = 'coinquest.wall'
const LOOPBACK = new Set(['localhost', '127.0.0.1', '[::1]'])

/** The reason beside a text field at the wall. */
export const WALL_TEXT_REASON = 'Use the laptop or a phone to type here.'

/** The reason on an act that needs typing to complete, at the wall. */
export const WALL_ACT_REASON = 'Use the laptop or a phone.'

/**
 * Where money the child adds came from, offered to tap at the wall in place
 * of typing. The label chosen is stored as the note, exactly as if typed.
 * Laptops and phones keep the free-text field. Change the list here.
 */
export const MONEY_SOURCES = [
  'Birthday',
  'Christmas',
  'Gift from family',
  'Sold something',
  'Other',
] as const

function remembered(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

function remember(value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(STORAGE_KEY)
    else window.localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // Storage refused: the override lasts for this page only.
  }
}

/** The immediate parent's origin when framed, or null at the top level. */
function parentOrigin(): string | null {
  if (window.top === window.self) return null
  const ancestors = window.location.ancestorOrigins
  if (ancestors && ancestors.length > 0) return ancestors[0]
  return document.referrer || null
}

function framedByLoopback(): boolean {
  const origin = parentOrigin()
  if (!origin) return false
  try {
    return LOOPBACK.has(new URL(origin).hostname)
  } catch {
    return false
  }
}

export function detectWall(): boolean {
  const asked = new URLSearchParams(window.location.search).get('wall')
  if (asked === 'on' || asked === 'off') remember(asked)
  else if (asked === 'auto') remember(null)
  const override = asked === 'on' || asked === 'off' ? asked : remembered()
  if (override === 'on') return true
  if (override === 'off') return false
  return framedByLoopback()
}

const AT_WALL = detectWall()

/** True on the kitchen wall. Read in render; it never changes. */
export function useWall(): boolean {
  return AT_WALL
}
