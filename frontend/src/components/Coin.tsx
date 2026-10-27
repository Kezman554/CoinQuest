/**
 * The coin: our own drawing, in the spirit of a platform game and copied from
 * none (DESIGN.md: no Nintendo artwork). A gold rim, a lighter face with an
 * inner ring, and a mark — a £ beside the money figure, a tick on a finished
 * chore.
 *
 * Decoration only. The figure beside it, or the word "Done" beside the tick,
 * says everything the coin does, so it is hidden from assistive technology.
 * Its colours come from CSS by class (App.css, "The coin"), never from
 * attributes here, so the token block stays the only place a colour is named
 * and a past week can mute it from the outside.
 */

export function Coin({ mark = 'pound', className = '' }: { mark?: 'pound' | 'tick'; className?: string }) {
  return (
    <svg
      className={`coin coin-${mark} ${className}`.trim()}
      viewBox="0 0 64 64"
      aria-hidden="true"
      focusable="false"
    >
      <circle className="coin-rim" cx="32" cy="32" r="29" />
      <circle className="coin-face" cx="32" cy="32" r="20" />
      {mark === 'pound' ? (
        <text className="coin-mark" x="32" y="43" textAnchor="middle">
          £
        </text>
      ) : (
        <path className="coin-tick" d="M22 33l7 7 14-15" />
      )}
    </svg>
  )
}
