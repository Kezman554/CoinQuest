/**
 * A second parent, with their own PIN (app/services/authorisation.py).
 *
 * Each configured parent's PIN proves which of them is acting, and the parent
 * view names them for it: "Confirmed 1 claim — by E2E Second". Rows recorded
 * before parents had names say "parent", and read as "a parent". The child's
 * wall shows no names at all.
 */

import { expect, test } from '@playwright/test'

test("the second parent's PIN confirms a claim, and the parent view names them", async ({ page }) => {
  await page.goto('/')
  await page.getByText('E2E Kid').waitFor()

  // Friday's chore, claimed on the wall — untouched by every other spec.
  const friday = page.locator('.day', { hasText: 'Friday' })
  await friday.getByRole('button', { name: /I've done it/ }).first().click()
  await expect(friday.locator('.chore-claimed')).toBeVisible()

  await page.getByRole('button', { name: 'Parent' }).click()
  const item = page.locator('li.queue-item').first()
  await item.locator('button.button-yes').click()
  await page.locator('.batch').getByRole('button', { name: 'Confirm' }).click()

  const dialog = page.locator('.dialog-backdrop')
  await page.locator('#pin').fill('1111')
  await dialog.getByRole('button', { name: 'Confirm the batch' }).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.locator('.last-batch')).toHaveText('Confirmed 1 claim — by E2E Second.')

  // Back on the wall, the chore is done, and no parent is named anywhere.
  await page.getByRole('button', { name: 'Back to the week' }).first().click()
  await expect(friday.locator('.chore-confirmed').first()).toBeVisible()
  await expect(page.locator('body')).not.toContainText('E2E Second')
  await expect(page.locator('body')).not.toContainText('E2E Parent')
})

test('a month settled before parents had names reads as "a parent"', async ({ page }) => {
  await page.route('**/api/savings/match', (route) =>
    route.fulfill({
      json: [
        {
          id: 1,
          period_start: '2026-08-01',
          period_end: '2026-08-31',
          balance_low_pence: 2000,
          had_withdrawal: false,
          rate_percent: 5,
          cap_pence: 10000,
          match_pence: 100,
          settled_by: 'parent',
          settled_at: '2026-09-02T18:00:00',
        },
      ],
    }),
  )
  await page.goto('/')
  await page.getByRole('button', { name: 'Parent' }).click()
  await page.getByRole('tab', { name: 'Savings' }).click()
  await expect(page.getByText(/settled .* by a parent\./)).toBeVisible()
})
