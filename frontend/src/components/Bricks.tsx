/**
 * The brick strip along the bottom of the wall: decoration, carrying nothing.
 *
 * Fixed to the viewport's bottom edge and drawn behind the page (z-index -1
 * in App.css), so it takes no height from the 1280x800 layout and covers
 * nothing — anything that reaches the bottom of the screen is drawn over it.
 * Courses of bricks offset by half a brick, with mortar joints; both colours
 * are tokens, applied by class.
 */

export function Bricks() {
  return (
    <svg className="bricks" aria-hidden="true" focusable="false">
      <defs>
        <pattern id="brick-course" width="48" height="24" patternUnits="userSpaceOnUse">
          <rect className="brick-face" width="48" height="24" />
          <path className="brick-joint" d="M0 1H48M0 12H48M24 1V12M0 12V24M48 12V24" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#brick-course)" />
    </svg>
  )
}
