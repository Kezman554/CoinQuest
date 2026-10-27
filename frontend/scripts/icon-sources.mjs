// Which icon source each output is made from — shared by make-icons.mjs,
// which copies FAVICON_SOURCE to public/favicon.svg, and check-literals.mjs,
// which holds public/favicon.svg to being an exact copy of it. One place, so
// the check always points at the file the favicon really comes from.

/** coin-small.svg's shapes plus the two eyes: the favicon and the 32px PNG. */
export const FAVICON_SOURCE = 'icons/coin-32.svg'
