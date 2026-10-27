/**
 * The mode the page is in, and the sun/moon button's flip of it.
 *
 * The root's data-theme is already right before React starts (index.html
 * runs the same modeFor); this keeps it right afterwards: it re-reads the
 * clock every RECHECK_MS, so the wall goes to night at 19:00 without a
 * reload, and it applies the button's override.
 *
 * Storage is the browser's own, and may not be there at all — a private
 * window, blocked site data. Every read and write is wrapped: a failed read
 * is no override, so the clock decides; a failed write still flips the
 * mode, held in memory until the next switch.
 */

import { useCallback, useEffect, useState } from 'react'

import { MODE_KEY, NIGHT, clockMode, modeFor, nextSwitch } from './theme'
import type { Mode, Override } from './theme'

/** Under a minute, so a switch is never more than this late. */
export const RECHECK_MS = 30_000

function readStored(): string | null {
  try {
    return localStorage.getItem(MODE_KEY)
  } catch {
    return null
  }
}

function writeStored(override: Override | null) {
  try {
    if (override) localStorage.setItem(MODE_KEY, JSON.stringify(override))
    else localStorage.removeItem(MODE_KEY)
  } catch {
    // Unavailable: the override is held in memory instead.
  }
}

function expired(stored: string | null, now: number): boolean {
  if (!stored) return false
  try {
    return !(JSON.parse(stored).until > now)
  } catch {
    return true
  }
}

export function useMode(): { mode: Mode; toggle: () => void } {
  const [stored, setStored] = useState<string | null>(readStored)
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), RECHECK_MS)
    return () => window.clearInterval(timer)
  }, [])

  const mode = modeFor(now, NIGHT, stored)

  useEffect(() => {
    document.documentElement.dataset.theme = mode
  }, [mode])

  // Past its switch, an override clears itself and the clock decides again.
  // modeFor already ignores it; this takes it out of storage too.
  useEffect(() => {
    if (expired(stored, now)) writeStored(null)
  }, [stored, now])

  const toggle = useCallback(() => {
    const at = Date.now()
    const wanted: Mode = modeFor(at, NIGHT, stored) === 'day' ? 'night' : 'day'
    // Flipping back to what the clock says is no override at all.
    const override: Override | null =
      wanted === clockMode(at, NIGHT) ? null : { mode: wanted, until: nextSwitch(at, NIGHT) }
    writeStored(override)
    setStored(override && JSON.stringify(override))
    setNow(at)
  }, [stored])

  return { mode, toggle }
}
