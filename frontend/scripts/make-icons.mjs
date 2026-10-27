// Generate CoinQuest's icons from the three sources in icons/ (DESIGN.md, Icon).
//
//   public/favicon.svg          coin-32.svg, as it is
//   public/favicon-32.png       coin-32.svg at 32px
//   public/favicon-16.png       coin-small.svg at 16px
//   public/apple-touch-icon.png coin.svg at 180px, on a solid ground (the day
//                               value, read from the token block) — iOS fills
//                               transparency with black
//
// The sources are our own drawing: a gold coin with a raised star with two
// eyes. coin-small.svg drops the rim, and the eyes that would be one grey
// pixel at 16; coin-32.svg is coin-small.svg with the eyes back, for 32px
// and the scalable favicon. Which source the favicon comes from is set once,
// in icon-sources.mjs, which the literal check reads too. The sources and
// favicon.svg are the only files outside the token block with literal
// colours, and check:literals holds favicon.svg to being an exact copy of
// its source — so edit icons/, then run `npm run icons`.
//
// Rasterised by the Chromium that Playwright already installs, so this adds
// no dependency and nothing native to build. The PNGs are committed; the
// container build never runs this.

import { copyFileSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

import { FAVICON_SOURCE } from './icon-sources.mjs'

const at = (path) => fileURLToPath(new URL(`../${path}`, import.meta.url))

const coin = readFileSync(at('icons/coin.svg'), 'utf8').trim()
const small = readFileSync(at('icons/coin-small.svg'), 'utf8').trim()
const favicon = readFileSync(at(FAVICON_SOURCE), 'utf8').trim()

const css = readFileSync(at('src/index.css'), 'utf8')
const ground = css.match(/tokens:start[\s\S]*?--ground:\s*(#[0-9a-fA-F]{6})/)?.[1]
if (!ground) throw new Error('No --ground in the token block of src/index.css')

copyFileSync(at(FAVICON_SOURCE), at('public/favicon.svg'))

const browser = await chromium.launch()
const page = await browser.newPage({ deviceScaleFactor: 1 })

/** Render `svg` at `drawn` px, centred on a `size` px square. */
async function png(svg, size, file, { background = null, drawn = size } = {}) {
  await page.setViewportSize({ width: size, height: size })
  const sized = svg.replace('<svg ', `<svg width="${drawn}" height="${drawn}" `)
  await page.setContent(
    `<!doctype html><html><body style="margin:0;width:${size}px;height:${size}px;` +
      `display:grid;place-items:center;background:${background ?? 'transparent'}">${sized}</body></html>`,
  )
  await page.screenshot({ path: at(file), omitBackground: !background, clip: { x: 0, y: 0, width: size, height: size } })
  console.log(`  ${file}  ${size}x${size}`)
}

console.log('icons — from icons/coin.svg, icons/coin-32.svg and icons/coin-small.svg:')
console.log(`  public/favicon.svg  (${FAVICON_SOURCE})`)
await png(favicon, 32, 'public/favicon-32.png')
await png(small, 16, 'public/favicon-16.png')
// iOS rounds the corners itself; the coin sits inside them, on the sky.
await png(coin, 180, 'public/apple-touch-icon.png', { background: ground, drawn: 148 })
await browser.close()
