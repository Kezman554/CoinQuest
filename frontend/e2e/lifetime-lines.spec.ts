/**
 * The Lifetime chart's three lines (Session AT): real, if nothing had ever
 * been withdrawn, and if every week's pay had been saved.
 *
 * A layout and framing fact, so it needs a rendered page: the third line is
 * drawn, dotted, and named in the legend; neither what-if line carries a
 * figure of its own, and nothing is shaded beside them — the page is about how money grows when
 * it is left alone, never about money lost. The history is fixed here, the
 * way the server would send nine months of it, so the result does not
 * depend on what earlier specs left in the scratch database.
 */

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

type Point = { occurred_on: string; balance_pence: number }

/** Month ends from February to October, each line a little above the one
 * before it — the shape the server's replay gives. */
function line(start: number, step: number, growth: number): Point[] {
  const points: Point[] = []
  let balance = start
  for (let month = 2; month <= 10; month += 1) {
    balance = Math.round((balance + step) * growth)
    const end = new Date(Date.UTC(2026, month, 0)).toISOString().slice(0, 10)
    points.push({ occurred_on: end, balance_pence: balance })
  }
  return points
}

const HISTORY = {
  total_earned_pence: 162_00,
  savings_breakdown: { from_payday_pence: 54_00, from_gifts_pence: 25_00, from_match_pence: 6_10 },
  real: line(10_00, 450, 1.0),
  counterfactual: line(10_00, 600, 1.05),
  saved_everything: line(10_00, 1800, 1.07),
}

async function openLifetime(page: Page, iso: string) {
  await page.clock.install({ time: new Date(iso) })
  await page.route('**/api/lifetime', (route) => route.fulfill({ json: HISTORY }))
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/')
  await page.locator('.total').waitFor()
  await page.getByRole('button', { name: 'Lifetime', exact: true }).click()
  await page.locator('.lifetime-chart').waitFor()
}

test('three lines, each told apart by shape as well as colour, and named', async ({ page }) => {
  await openLifetime(page, '2026-11-18T12:00:00Z')

  const chart = page.locator('.lifetime-chart')
  await expect(chart.locator('path.lifetime-line')).toHaveCount(3)
  const dashes = await chart.locator('path.lifetime-line').evaluateAll((paths) =>
    paths.map((path) => getComputedStyle(path).strokeDasharray),
  )
  expect(new Set(dashes).size).toBe(3)

  await expect(page.locator('.lifetime-legend li')).toHaveText([
    'Real',
    'If nothing had ever been withdrawn',
    "If every week's pay had been saved",
  ])
})

test('neither what-if line has a figure, and nothing is shaded as a loss', async ({ page }) => {
  await openLifetime(page, '2026-11-18T12:00:00Z')

  const panel = page.locator('section.panel', { has: page.locator('.lifetime-chart') })
  // Only the real balance is a figure; the what-ifs are lines only.
  await expect(panel.locator('.figure-label')).toHaveText(['Real, today'])
  const last = (points: Point[]) => points[points.length - 1].balance_pence
  // Formatted the way the page formats money (all these are over £1).
  const pounds = (pence: number) =>
    pence % 100 === 0 ? `£${pence / 100}` : `£${(pence / 100).toFixed(2)}`
  for (const pence of [last(HISTORY.counterfactual), last(HISTORY.saved_everything)]) {
    await expect(panel.locator('.figures')).not.toContainText(pounds(pence))
  }
  // The lines keep their names in the legend.
  await expect(panel.locator('.lifetime-legend li')).toContainText([
    'If nothing had ever been withdrawn',
    "If every week's pay had been saved",
  ])

  // Lines only: no area, and no path filled in.
  const chart = page.locator('.lifetime-chart svg')
  await expect(chart.locator('polygon, rect')).toHaveCount(0)
  const fills = await chart
    .locator('path')
    .evaluateAll((paths) => paths.map((path) => getComputedStyle(path).fill))
  expect(fills.every((fill) => fill === 'none')).toBe(true)
})

test('day and night both draw it from tokens', async ({ page }) => {
  for (const [iso, mode] of [
    ['2026-11-18T12:00:00Z', 'day'],
    ['2026-11-18T20:30:00Z', 'night'],
  ] as const) {
    await openLifetime(page, iso)
    await expect(page.locator('html')).toHaveAttribute('data-theme', mode)
    const stroke = await page
      .locator('path.lifetime-line-saved')
      .evaluate((path) => getComputedStyle(path).stroke)
    const waiting = await page.evaluate(() =>
      getComputedStyle(document.documentElement).getPropertyValue('--waiting').trim(),
    )
    const toRgb = await page.evaluate((hex) => {
      const probe = document.createElement('span')
      probe.style.color = hex
      document.body.append(probe)
      const rgb = getComputedStyle(probe).color
      probe.remove()
      return rgb
    }, waiting)
    expect(stroke).toBe(toRgb)
  }
})
