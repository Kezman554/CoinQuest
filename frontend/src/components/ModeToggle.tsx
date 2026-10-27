/**
 * The sun/moon button in the title row (DESIGN.md, Modes).
 *
 * It shows, and its label names, the mode it switches to: a moon by day
 * ("Switch to night"), a sun by night. A press holds until the next
 * scheduled switch and then the clock decides again — see useMode.ts.
 * Our own stroke drawings, coloured by the button's text colour.
 */

import type { Mode } from '../theme'

export function ModeToggle({ mode, onToggle }: { mode: Mode; onToggle: () => void }) {
  const to = mode === 'day' ? 'night' : 'day'
  return (
    <button type="button" className="button mode-toggle" aria-label={`Switch to ${to}`} onClick={onToggle}>
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        {to === 'night' ? (
          <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
        ) : (
          <>
            <circle cx="12" cy="12" r="4.5" />
            <path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" />
          </>
        )}
      </svg>
    </button>
  )
}
