// Measure the palette against DESIGN.md's contrast floors, in both modes.
//
// Text must reach 4.725:1 and non-text 3.15:1 — the WCAG floors of 4.5 and 3
// with 5% to spare, so a value nudged on the kitchen panel does not slip
// straight under. The colours are read from the token block in src/index.css,
// day from `:root` and night as day overlaid with `[data-theme='night']`, so
// the script measures what the page actually uses.
//
// Three kinds of measurement, following DESIGN.md's token table ("Used for")
// and its Contrast floors section:
//
//   text      words on the fill they are written on.
//   named     the non-text pairings DESIGN.md names one by one, measured
//             exactly as named.
//   boundary  a component against the surface it sits on. WCAG 1.4.11 asks
//             that a component be told apart from what is around it, and
//             either its fill or its edge may do that — a gold card on the
//             sky is told apart by its outline, not its gold. So a boundary
//             passes when the better of fill and edge reaches the floor. An
//             edge is not measured against its own fill: that is not what
//             makes a shape visible.
//
// Every colour token must be accounted for: measured somewhere, or listed
// under DECORATION with the reason it carries nothing. A token that is neither
// fails the run — a colour nobody checked is how a palette drifts.
//
// Plain Node and no dependencies.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const TEXT = 4.725
const NON_TEXT = 3.15

// [foreground, background, what it is]
const TEXT_PAIRS = [
  ['ink', 'ground', 'title, dates and headings on the sky'],
  ['ink', 'panel', 'text on day tiles, the owed card, the any-time card'],
  ['ink', 'panel-today', "text on today's tile"],
  ['ink', 'raised', 'labels on neutral buttons'],
  ['ink', 'settled', 'the money card on a past week'],
  ['ink-soft', 'ground', 'secondary text on the sky'],
  ['ink-soft', 'panel', 'dates and secondary text on panels'],
  ['ink-soft', 'panel-today', "the date on today's tile"],
  ['ink-soft', 'raised', 'secondary text on neutral buttons'],
  ['on-gold', 'gold', 'the money card, the bonus tag'],
  ['on-action', 'action', '"I\'ve done it", "Have another go"'],
  ['done', 'done-bg', 'a finished chore'],
  ['done', 'panel', '"All paid up" on the owed card'],
  ['waiting', 'waiting-bg', 'waiting to be checked'],
  ['danger', 'danger-bg', 'missed, refused, chores at risk, the last day'],
  ['on-today', 'today', 'the word TODAY on its tag'],
  ['disabled', 'disabled-bg', '"This is the latest" and forbidden controls'],
  ['on-gold-chip-ink', 'on-gold-chip', 'a chip, the make-good box, on the money card'],
  ['on-gold-chip-ink-soft', 'on-gold-chip', "a chip's label on the money card"],
  ['on-gold-done', 'on-gold-done-bg', 'the Chores chip once won, a put-right notice'],
  ['on-gold-danger', 'on-gold-danger-bg', 'the Chores chip at risk, the missed-chore notice'],
  // The other screens (Savings, Lifetime, the parent view, the PIN dialog).
  ['danger', 'raised', 'a refusing or money-removing button (reject, void, mark missed)'],
  ['danger', 'panel', 'a refusal or error in a panel or the PIN dialog; the reopen heading'],
  ['waiting', 'panel', "a reconciliation that does not agree"],
  ['ink-soft', 'settled', "a retired chore's cadence, on its settled row"],
]

// [colour, background, what it is] — DESIGN.md's Contrast floors, by name.
const EDGE_PAIRS = [
  ['today', 'panel-today', "the TODAY tag's pill on today's tile"],
  ['today-edge', 'ground', "today's tile outline on the sky (tightest by day)"],
  ['panel-edge', 'ground', 'a panel outline on the sky (tightest at night)'],
  ['disabled-edge', 'ground', 'a disabled control on the sky (tight in both modes)'],
  ['waiting-edge', 'waiting-bg', 'the dashed waiting edge (check whenever either moves)'],
  // The lifetime chart, each stroke on the panel it is drawn on.
  ['ink', 'panel', 'the lifetime chart: the real balance line'],
  ['done', 'panel', 'the lifetime chart: the never-withdrawn line (dashed)'],
  ['ink-soft', 'panel', "the lifetime chart: its baseline"],
]

// [fill, edge, surface, what it is] — passes on the better of fill and edge.
const BOUNDARIES = [
  ['panel', 'panel-edge', 'ground', 'a day tile, the owed card, on the sky'],
  ['panel-today', 'today-edge', 'ground', "today's tile on the sky"],
  ['gold', 'outline', 'ground', 'the money card on the sky'],
  ['raised', 'control-edge', 'ground', 'a neutral button in the title row'],
  ['raised', 'control-edge', 'panel', 'a neutral button on a panel'],
  ['disabled-bg', 'disabled-edge', 'ground', '"This is the latest" in the title row'],
  ['action', 'outline', 'panel', '"I\'ve done it" on a day tile'],
  ['action', 'outline', 'panel-today', "\"I've done it\" on today's tile"],
  ['done-bg', 'done-edge', 'panel', 'a finished chore on a day tile'],
  ['waiting-bg', 'waiting-edge', 'panel', 'a waiting chore on a day tile'],
  ['danger-bg', 'danger-edge', 'panel', 'a missed chore on a day tile'],
  ['raised', 'danger-edge', 'danger-bg', '"Not missed after all" inside a missed chore'],
  ['done-edge', 'done-edge', 'panel', 'the savings progress bar on its panel'],
  ['on-gold-chip', 'on-gold-chip-edge', 'gold', 'a chip, the make-good box, on the money card'],
  ['gold', 'outline', 'panel', 'the savings match amount on the owed card'],
  ['on-gold-done-bg', 'on-gold-done-edge', 'gold', 'the Chores chip once won, on the money card'],
  ['on-gold-danger-bg', 'on-gold-danger-edge', 'gold', 'the Chores chip at risk, the notice, on the money card'],
  // The other screens.
  ['raised', 'danger-edge', 'panel', 'a refusing or money-removing button on a panel'],
  ['raised', 'control-edge', 'done-bg', 'Yes / No on a queue row ruled yes'],
  ['raised', 'danger-edge', 'done-bg', 'No on a queue row ruled yes'],
  ['raised', 'done-edge', 'done-bg', 'Yes, chosen, on its row'],
  ['raised', 'control-edge', 'danger-bg', 'Yes on a queue row ruled no'],
  ['waiting-bg', 'waiting-edge', 'raised', 'the waiting count on a parent tab'],
  ['danger-bg', 'danger-edge', 'panel', 'chore money at risk, a figure in the parent view'],
]

// Colour tokens that are never read: each with why it may go unmeasured.
const DECORATION = {
  brick: 'the bottom strip; DESIGN: decoration, carries nothing',
  mortar: "the bottom strip's joints; DESIGN: decoration, carries nothing",
  'coin-light': "the coin's face; DESIGN: decoration",
  'coin-dark': "the coin's inner ring; DESIGN: decoration",
  shadow: 'hard offset shadows; a depth cue under shapes whose boundaries are measured',
}

// --- the palette, as the page has it -------------------------------------------

const css = readFileSync(fileURLToPath(new URL('../src/index.css', import.meta.url)), 'utf8')
const block = css.match(/\/\*\s*tokens:start\s*\*\/([\s\S]*?)\/\*\s*tokens:end\s*\*\//)
if (!block) {
  console.error('check:contrast — no token block in src/index.css')
  process.exit(1)
}
const tokens = block[1].replace(/\/\*[\s\S]*?\*\//g, '')
const rules = [...tokens.matchAll(/([^{}]+)\{([^}]*)\}/g)].map((m) => ({ selector: m[1], body: m[2] }))

function colours(body) {
  const out = {}
  for (const m of body.matchAll(/--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) out[m[1]] = m[2].toLowerCase()
  return out
}

const dayRule = rules.find((r) => !r.selector.includes('night'))
const nightRule = rules.find((r) => r.selector.includes('night'))
if (!dayRule || !nightRule) {
  console.error('check:contrast — expected a day rule and a night rule in the token block')
  process.exit(1)
}
const day = colours(dayRule.body)
const night = { ...day, ...colours(nightRule.body) }

// Any other colour notation in the block is a token this script cannot read.
const unreadable = [...tokens.matchAll(/--([\w-]+)\s*:\s*(rgb|hsl|#[0-9a-fA-F]{3}\b|#[0-9a-fA-F]{8}\b)/g)]

// --- WCAG relative luminance and contrast ---------------------------------------

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

// --- run --------------------------------------------------------------------------

const failures = []
const lines = []
const measured = new Set()

function line(pass, kind, r, floor, label, what) {
  lines.push(`  ${pass ? 'pass' : 'FAIL'}  ${kind.padEnd(8)}  ${r.toFixed(2).padStart(5)}:1 ≥ ${String(floor).padEnd(5)}  ${label.padEnd(38)} ${what}`)
}

function have(mode, palette, names, what) {
  const missing = names.filter((n) => !palette[n])
  if (missing.length) failures.push(`${mode}: ${what} — no token ${missing.map((n) => `--${n}`).join(', ')}`)
  return missing.length === 0
}

for (const [mode, palette] of [['day', day], ['night', night]]) {
  lines.push(`\n${mode}`)
  for (const [fg, bg, what] of TEXT_PAIRS) {
    measured.add(fg).add(bg)
    if (!have(mode, palette, [fg, bg], what)) continue
    const r = ratio(palette[fg], palette[bg])
    line(r >= TEXT, 'text', r, TEXT, `${fg} on ${bg}`, what)
    if (r < TEXT) failures.push(`${mode}: text ${fg} on ${bg} is ${r.toFixed(2)}:1, under ${TEXT} (${what})`)
  }
  for (const [edge, bg, what] of EDGE_PAIRS) {
    measured.add(edge).add(bg)
    if (!have(mode, palette, [edge, bg], what)) continue
    const r = ratio(palette[edge], palette[bg])
    line(r >= NON_TEXT, 'named', r, NON_TEXT, `${edge} on ${bg}`, what)
    if (r < NON_TEXT) failures.push(`${mode}: ${edge} on ${bg} is ${r.toFixed(2)}:1, under ${NON_TEXT} (${what})`)
  }
  for (const [fill, edge, surface, what] of BOUNDARIES) {
    measured.add(fill).add(edge).add(surface)
    if (!have(mode, palette, [fill, edge, surface], what)) continue
    const byFill = ratio(palette[fill], palette[surface])
    const byEdge = ratio(palette[edge], palette[surface])
    const r = Math.max(byFill, byEdge)
    const by = byFill >= byEdge ? fill : edge
    line(r >= NON_TEXT, 'boundary', r, NON_TEXT, `${fill}|${edge} on ${surface} (by ${by})`, what)
    if (r < NON_TEXT) {
      failures.push(`${mode}: boundary ${fill}|${edge} on ${surface} is ${r.toFixed(2)}:1 at best, under ${NON_TEXT} (${what})`)
    }
  }
}

for (const token of Object.keys(day)) {
  if (!measured.has(token) && !DECORATION[token]) {
    failures.push(`--${token} is neither measured nor listed as decoration with a reason`)
  }
}
for (const token of Object.keys(DECORATION)) {
  if (!day[token]) failures.push(`decoration "${token}" is not a token in src/index.css — remove it from the list`)
}
for (const m of unreadable) failures.push(`--${m[1]} is not a six-digit hex value, so it cannot be measured`)

console.log(lines.join('\n'))
console.log(`\ndecoration (unmeasured): ${Object.entries(DECORATION).map(([k, why]) => `\n  ${k} — ${why}`).join('')}`)

if (failures.length) {
  console.error(`\ncheck:contrast — ${failures.length} failure(s):`)
  for (const f of failures) console.error(`  ${f}`)
  process.exit(1)
}
const count = TEXT_PAIRS.length + EDGE_PAIRS.length + BOUNDARIES.length
console.log(`\ncheck:contrast — all ${count} measurements pass in both modes; every colour token accounted for.`)
