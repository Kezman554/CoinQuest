/**
 * Claiming a chore on a past day of a week that has not settled.
 *
 * The defect this guards against was entirely in the rendered page: the API
 * accepted the claim all along, and the week view locked every week paged
 * back to, open or not, so a chore done last Wednesday and ticked by nobody
 * had no control anywhere once Sunday came. A unit test of POST /api/claims
 * could never have seen it. What has to be true is that the tile on the
 * previous week carries the same button the current week's does, that the
 * banner says so, and that a settled week would not — the last of which the
 * pytest suite proves at the API, since nothing in this seed is settled.
 *
 * Runs last: Playwright takes spec files in name order against one shared
 * database, and confirm-flow.spec.ts counts the parent's queue before this
 * adds to it.
 */

import { expect, test } from '@playwright/test'

test.describe('a past week that has not settled', () => {
  test('its day tiles still take a claim, and the claim survives a reload', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByText('E2E Kid').waitFor()

    // Back one week. The seed's previous week is open and never settled.
    await page.locator('.week-nav button').first().click()
    const banner = page.locator('.notice-away')
    await expect(banner).toContainText('Not the current week')
    // Said out loud, with the caution: a late tick is about its own day.
    await expect(banner).toContainText('you can still tick it now')
    await expect(banner).toContainText('counts for this week, not for last')

    // Last Wednesday: untouched in the seed, and long gone by now. The row
    // is the button, exactly as it is on the current week.
    const wednesday = page.locator('.day', { hasText: 'Wednesday' })
    const bed = wednesday.locator('.chore-claimable', { hasText: 'Make bed' })
    await expect(bed).toBeVisible()
    await expect(bed).toContainText("I've done it")
    await bed.click()

    await expect(wednesday.locator('.chore-claimed')).toContainText('Waiting to be checked')

    // The database's, not the page's — and still on the previous week.
    await page.reload()
    await page.getByText('E2E Kid').waitFor()
    await page.locator('.week-nav button').first().click()
    await expect(
      page.locator('.day', { hasText: 'Wednesday' }).locator('.chore-claimed'),
    ).toContainText('Waiting to be checked')

    // And it reaches the parent's queue by the one path to confirmed.
    await page.getByRole('button', { name: 'Back to this week' }).click()
    await page.getByRole('button', { name: 'Parent' }).click()
    await expect(page.getByText('Claims waiting')).toBeVisible()
    await expect(page.locator('li.queue-item', { hasText: 'Make bed' })).toHaveCount(1)
  })
})
