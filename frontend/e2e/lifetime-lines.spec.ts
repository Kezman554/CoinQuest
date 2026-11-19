/**
 * The Lifetime chart's three lines (Session AT): real, if nothing had ever
 * been withdrawn, and if every week's pay had been saved.
 *
 * A layout and framing fact, so it needs a rendered page: the third line is
 * drawn, dotted, and named in the key; every line's figure sits beside its
 * swatch and is its line's final balance; the axis is marked in pounds; and
 * nothing is shaded beside the lines — the page is about how money grows when
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

  await expect(page.locator('.lifetime-legend-label')).toHaveText([
    'Real, today',
    'If nothing had ever been withdrawn',
    "If every week's pay had been saved",
  ])
})

/** Formatted the way the page formats money (every figure here is over £1). */
function pounds(pence: number): string {
  return pence % 100 === 0 ? `£${pence / 100}` : `£${(pence / 100).toFixed(2)}`
}

const final = (points: Point[]) => points[points.length - 1].balance_pence

test("each line's figure is its final point, beside its swatch, in its colour", async ({ page }) => {
  await openLifetime(page, '2026-11-18T12:00:00Z')

  const key = page.locator('.lifetime-legend')
  for (const [kind, points, colour] of [
    ['real', HISTORY.real, '--ink'],
    ['counterfactual', HISTORY.counterfactual, '--done'],
    ['saved', HISTORY.saved_everything, '--waiting'],
  ] as const) {
    const entry = key.locator(`li.lifetime-legend-${kind}`)
    const value = entry.locator('.lifetime-legend-value')
    await expect(value).toHaveText(pounds(final(points)))
    const [ink, token] = await value.evaluate((element, name) => {
      const probe = document.createElement('span')
      probe.style.color = `var(${name})`
      document.body.append(probe)
      const resolved = getComputedStyle(probe).color
      probe.remove()
      return [getComputedStyle(element).color, resolved]
    }, colour)
    expect(ink).toBe(token)
  }
  // Three lines, three figures: no figure stands apart from the key.
  await expect(key.locator('.lifetime-legend-value')).toHaveCount(3)
})

test('the axis is marked in pounds, up to at least the highest point', async ({ page }) => {
  await openLifetime(page, '2026-11-18T12:00:00Z')

  const marks = await page.locator('.lifetime-axis li').allTextContents()
  expect(marks[0]).toBe('£0')
  expect(marks.every((mark) => /^£\d+(\.\d\d)?$/.test(mark))).toBe(true)
  const top = Number(marks[marks.length - 1].slice(1)) * 100
  const highest = Math.max(
    ...[...HISTORY.real, ...HISTORY.counterfactual, ...HISTORY.saved_everything].map(
      (point) => point.balance_pence,
    ),
  )
  expect(top).toBeGreaterThanOrEqual(highest)
  // Each mark sits level with its hairline: the top one at the top of the drawing.
  const axis = await page.locator('.lifetime-axis li').last().boundingBox()
  const line = await page.locator('.lifetime-chart-mark').last().boundingBox()
  expect(Math.abs(axis!.y + axis!.height / 2 - (line!.y + line!.height / 2))).toBeLessThan(3)
})

test('the headline and the savings breakdown say what they count', async ({ page }) => {
  await openLifetime(page, '2026-11-18T12:00:00Z')
  await expect(page.locator('.total-label')).toHaveText('Earned from chores and rewards')
  await expect(page.locator('.total-amount')).toHaveText(pounds(HISTORY.total_earned_pence))
  await expect(page.getByText('Banked from your pay')).toBeVisible()
  await expect(page.getByText('Total earned to date')).toHaveCount(0)
  await expect(page.getByText('From payday', { exact: true })).toHaveCount(0)
})

test('nothing is shaded between the lines', async ({ page }) => {
  await openLifetime(page, '2026-11-18T12:00:00Z')

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
