/**
 * Day and night on the wall (DESIGN.md, Modes): the clock decides, a
 * sun/moon button overrides until the next switch, and the page is already
 * in the right mode before it paints.
 *
 * Driven with Playwright's clock control, so "it is 19:30 in London" is a
 * fact of the test rather than of the machine running it. Late October 2026
 * is GMT, so the UTC times below are London times; the one spring case is
 * there for the clock change.
 */

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const KEY = 'coinquest.mode'
const theme = (page: Page) => page.locator('html')

async function openAt(page: Page, iso: string) {
  await page.clock.install({ time: new Date(iso) })
  await page.goto('/')
  await page.locator('.total').waitFor()
}

test.describe('the clock decides', () => {
  test('before 19:00 it is day', async ({ page }) => {
    await openAt(page, '2026-10-27T18:30:00Z')
    await expect(theme(page)).toHaveAttribute('data-theme', 'day')
    await expect(page.getByRole('button', { name: 'Switch to night' })).toBeVisible()
  })

  test('after 19:00 it is night', async ({ page }) => {
    await openAt(page, '2026-10-27T19:30:00Z')
    await expect(theme(page)).toHaveAttribute('data-theme', 'night')
    await expect(page.getByRole('button', { name: 'Switch to day' })).toBeVisible()
  })

  test('still night before 07:00, and day again after it', async ({ page }) => {
    await openAt(page, '2026-10-28T06:30:00Z')
    await expect(theme(page)).toHaveAttribute('data-theme', 'night')
    await page.clock.fastForward('01:00:00')
    await expect(theme(page)).toHaveAttribute('data-theme', 'day')
  })

  test('the wall turns at 19:00 without a reload', async ({ page }) => {
    await openAt(page, '2026-10-27T18:59:00Z')
    await expect(theme(page)).toHaveAttribute('data-theme', 'day')
    await page.clock.fastForward('01:30')
    await expect(theme(page)).toHaveAttribute('data-theme', 'night')
  })
})

test.describe('the sun/moon button', () => {
  test('flips the mode until the next switch, survives a reload, then clears itself', async ({ page }) => {
    await openAt(page, '2026-10-27T10:00:00Z')
    await expect(theme(page)).toHaveAttribute('data-theme', 'day')

    await page.getByRole('button', { name: 'Switch to night' }).click()
    await expect(theme(page)).toHaveAttribute('data-theme', 'night')
    const stored = JSON.parse((await page.evaluate((k) => localStorage.getItem(k), KEY)) as string)
    expect(stored).toEqual({ mode: 'night', until: Date.parse('2026-10-27T19:00:00Z') })

    // Held across a reload — set before paint by index.html's own script.
    await page.reload()
    await expect(theme(page)).toHaveAttribute('data-theme', 'night')

    // Past 19:00 the override has run out: gone from storage, and the clock
    // decides — night, by now, and day again the next morning.
    await page.clock.fastForward('09:01:00')
    await expect(theme(page)).toHaveAttribute('data-theme', 'night')
    await expect.poll(() => page.evaluate((k) => localStorage.getItem(k), KEY)).toBeNull()
    await page.clock.fastForward('12:00:00')
    await expect(theme(page)).toHaveAttribute('data-theme', 'day')
  })

  test('pressed twice, it is back to the clock with nothing stored', async ({ page }) => {
    await openAt(page, '2026-10-27T10:00:00Z')
    await page.getByRole('button', { name: 'Switch to night' }).click()
    await page.getByRole('button', { name: 'Switch to day' }).click()
    await expect(theme(page)).toHaveAttribute('data-theme', 'day')
    expect(await page.evaluate((k) => localStorage.getItem(k), KEY)).toBeNull()
  })

  test('an override made the night the clocks go forward runs out at 07:00 BST', async ({ page }) => {
    // 28 March 2026, 20:00 GMT. The clocks go forward at 01:00 on the 29th,
    // so 07:00 that morning is 06:00 UTC, not 07:00.
    await openAt(page, '2026-03-28T20:00:00Z')
    await page.getByRole('button', { name: 'Switch to day' }).click()
    const stored = JSON.parse((await page.evaluate((k) => localStorage.getItem(k), KEY)) as string)
    expect(stored).toEqual({ mode: 'day', until: Date.parse('2026-03-29T06:00:00Z') })
  })
})

test('with storage throwing, the clock decides and the button still works', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await page.addInitScript(() => {
    const refuse = () => {
      throw new DOMException('Storage is disabled', 'SecurityError')
    }
    Storage.prototype.getItem = refuse
    Storage.prototype.setItem = refuse
    Storage.prototype.removeItem = refuse
  })
  await openAt(page, '2026-10-27T20:00:00Z')
  await expect(theme(page)).toHaveAttribute('data-theme', 'night')

  // Held in memory, since it cannot be stored.
  await page.getByRole('button', { name: 'Switch to day' }).click()
  await expect(theme(page)).toHaveAttribute('data-theme', 'day')
  expect(errors).toEqual([])
})

test('the mode is set before the app runs, so night never flashes day', async ({ page }) => {
  // No app at all: only index.html's inline script can have set it.
  await page.route('**/assets/*.js', (route) => route.abort())
  await page.clock.install({ time: new Date('2026-10-27T21:00:00Z') })
  await page.goto('/')
  await expect(theme(page)).toHaveAttribute('data-theme', 'night')
})

test('every screen follows the mode', async ({ page }) => {
  await openAt(page, '2026-10-27T21:00:00Z')
  const ground = () => page.evaluate(() => getComputedStyle(document.documentElement).backgroundColor)
  const night = await ground()
  expect(night).toBe('rgb(24, 32, 63)')

  for (const screen of ['Savings', 'Lifetime', 'Parent']) {
    await page.getByRole('button', { name: screen }).click()
    await expect(theme(page)).toHaveAttribute('data-theme', 'night')
    expect(await ground()).toBe(night)
    await page.getByRole('button', { name: 'Back to the week' }).first().click()
    await page.locator('.total').waitFor()
  }
})
