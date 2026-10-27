// Fail on a literal the design system should own.
//
// DESIGN.md's Enforcement rule: no hex colour, rgb()/hsl(), quoted font name
// or px border-radius outside the token block in src/index.css — the block
// between `/* tokens:start */` and `/* tokens:end */`. Everything else reaches
// the design through var(). CSS named colours (white, black, …) in a colour
// property count as literals too: they are the same thing under another name.
//
// Covers every .css, .tsx, .ts and .svg under src/, the .svg files in
// public/, and index.html:
//   - CSS: declarations only, so an ID selector (#root) or a media condition
//     is never mistaken for a value.
//   - TSX/TS: colour strings anywhere, and the inline-style keys that carry
//     design (color and friends, fontFamily, borderRadius — a bare number
//     there is px).
//   - SVG: hex colours anywhere, and rx/ry on <rect>, where they are corner
//     radii. On an ellipse rx/ry are the shape itself, not a rounding, and
//     are left alone.
//
// One exception, the icon (DESIGN.md, Icon): a favicon cannot read a CSS
// token, so its colours are written into the SVG. The sources in icons/ are
// the only files outside the token block allowed literal colours, and
// public/favicon.svg passes only while it is an exact copy of
// icons/coin-small.svg — `npm run icons` makes it so. Edit the source,
// never the copy.
//
// Plain Node and no dependencies, so `npm run check:literals` runs the same
// on Windows as on the Pi. Exit 1 with one line per finding.

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))

const NAMED = new Set(
  `aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue
  blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk
  crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki
  darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
  darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue
  dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite
  gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki
  lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
  lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen
  lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen
  magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen
  mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
  mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid
  palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum
  powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown
  seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen
  steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow
  yellowgreen`.split(/\s+/),
)

const COLOUR_PROPS = /^(color|background(-color|-image)?|border(-(top|right|bottom|left|block|inline))?(-color)?|outline(-color)?|fill|stroke|box-shadow|text-shadow|caret-color|accent-color|text-decoration(-color)?|column-rule(-color)?)$/

const HEX = /#[0-9a-fA-F]{3,8}\b/
const FUNC = /\b(rgba?|hsla?)\(/
const findings = []

function report(file, line, kind, text) {
  findings.push(`${relative(root, file).replaceAll('\\', '/')}:${line}  ${kind}  ${text.trim().slice(0, 90)}`)
}

/** Blank out comments, keeping every newline so line numbers hold. */
function blankComments(text) {
  return text.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '))
}

/** Blank the token block itself: it is where literals belong. */
function blankTokenBlock(text) {
  return text.replace(/\/\*\s*tokens:start\s*\*\/[\s\S]*?\/\*\s*tokens:end\s*\*\//g, (c) =>
    c.replace(/[^\n]/g, ' '),
  )
}

const lineOf = (text, index) => text.slice(0, index).split('\n').length

function checkCss(file) {
  const raw = readFileSync(file, 'utf8')
  const text = blankComments(blankTokenBlock(raw))
  const decl = /([a-zA-Z-]+)\s*:\s*([^;{}]*)(?=[;}])/g
  for (const m of text.matchAll(decl)) {
    const prop = m[1].toLowerCase()
    const value = m[2]
    const at = lineOf(text, m.index)
    const shown = `${prop}: ${value}`
    if (HEX.test(value)) report(file, at, 'hex', shown)
    if (FUNC.test(value)) report(file, at, 'rgb()', shown)
    if ((prop === 'font-family' || prop === 'font') && (/['"]/.test(value) || /\bsystem-ui\b/.test(value))) {
      report(file, at, 'font name', shown)
    }
    if (/radius$/.test(prop) && /\d(\.\d+)?px\b/.test(value)) report(file, at, 'px radius', shown)
    if (COLOUR_PROPS.test(prop)) {
      const words = value.replace(/var\([^)]*\)/g, '').toLowerCase().match(/[a-z]+/g) ?? []
      const named = words.find((w) => NAMED.has(w))
      if (named) report(file, at, `named colour (${named})`, shown)
    }
  }
}

function checkScript(file) {
  const lines = readFileSync(file, 'utf8').split('\n')
  let inBlock = false
  lines.forEach((line, i) => {
    const at = i + 1
    const trimmed = line.trim()
    if (inBlock) {
      if (trimmed.includes('*/')) inBlock = false
      return
    }
    if (trimmed.startsWith('/*')) {
      if (!trimmed.includes('*/')) inBlock = true
      return
    }
    if (trimmed.startsWith('//') || trimmed.startsWith('*')) return
    if (/['"`]\s*#[0-9a-fA-F]{3,8}\b/.test(line)) report(file, at, 'hex', line)
    if (FUNC.test(line)) report(file, at, 'rgb()', line)
    for (const m of line.matchAll(/\b(color|background|backgroundColor|borderColor|outlineColor|fill|stroke)\s*[:=]\s*\{?\s*['"`]([^'"`]*)['"`]/g)) {
      const words = m[2].replace(/var\([^)]*\)/g, '').toLowerCase().match(/[a-z]+/g) ?? []
      const named = words.find((w) => NAMED.has(w))
      if (named) report(file, at, `named colour (${named})`, line)
    }
    if (/\bfontFamily\s*[:=]\s*\{?\s*['"`](?!\s*var\()/.test(line)) report(file, at, 'font name', line)
    if (/\bborderRadius\s*:\s*(-?\d|['"`][^'"`]*\dpx)/.test(line)) report(file, at, 'px radius', line)
    if (/<rect\b[^>]*\b(rx|ry)\s*=\s*\{?\s*['"]?\s*-?\d/.test(line)) report(file, at, 'svg rx/ry', line)
  })
}

const ICONS = join(root, 'icons')
const FAVICON = join(root, 'public', 'favicon.svg')
const FAVICON_SOURCE = join(ICONS, 'coin-small.svg')

function checkSvg(file) {
  const text = readFileSync(file, 'utf8')
  if (file.startsWith(ICONS)) return
  if (file === FAVICON) {
    if (text !== readFileSync(FAVICON_SOURCE, 'utf8')) {
      report(file, 1, 'icon copy', 'differs from icons/coin-small.svg — edit the source and run `npm run icons`')
    }
    return
  }
  for (const m of text.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) {
    report(file, lineOf(text, m.index), 'hex', text.slice(Math.max(0, m.index - 24), m.index + 10))
  }
  for (const m of text.matchAll(/<rect\b[^>]*>/g)) {
    if (/\b(rx|ry)\s*=\s*"(?!\s*var\()[^"]*"/.test(m[0])) report(file, lineOf(text, m.index), 'svg rx/ry', m[0])
  }
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path, out)
    else out.push(path)
  }
  return out
}

const files = [...walk(join(root, 'src')), ...walk(join(root, 'public')), ...walk(ICONS), join(root, 'index.html')]
for (const file of files) {
  if (file.endsWith('.css')) checkCss(file)
  else if (/\.(tsx|ts|html)$/.test(file)) checkScript(file)
  else if (file.endsWith('.svg')) checkSvg(file)
}

if (findings.length) {
  console.error(`check:literals — ${findings.length} literal(s) outside the token block:\n`)
  for (const f of findings) console.error(`  ${f}`)
  console.error('\nUse a token from src/index.css (var(--…)); see DESIGN.md, Token roles.')
  process.exit(1)
}
console.log(`check:literals — clean: ${files.length} files, no literal outside the token block.`)
