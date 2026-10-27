/**
 * An ended month the savings match is waiting on stays on the wall until a
 * parent settles it, and settling clears it.
 *
 * Nothing settles itself (app.services.savings_match): the wall only reads
 * the due list, and the line goes away because a parent settled the month
 * with the PIN, not because time passed. Driven against the real backend:
 * the account opens on the first of last month, which makes last month an
 * ended, unsettled month with a match to pay.
 */

import { expect, test } from '@playwright/test'

function firstOfLastMonth(): { iso: string; month: string } {
  const now = new Date()
  const first = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1, 12))
  return {
    iso: first.toISOString().slice(0, 10),
    month: first.toLocaleDateString('en-GB', { month: 'long', timeZone: 'UTC' }),
  }
}

test('settling the month clears its interest line from the wall', async ({ page, request }) => {
  const last = firstOfLastMonth()
  const opened = await request.post('/api/savings/opening-balance', {
    data: { pin: '0000', amount_pence: 2000, occurred_on: last.iso },
  })
  expect(opened.status()).toBe(201)

  await page.goto('/')
  const line = page.locator('.owed-interest li', { hasText: `Interest for ${last.month}:` })
  await expect(line).toBeVisible()
  await expect(line).toContainText('going into your bank')
  // Kept apart from the cash: no weeks are owed in the seed, so no cash total
  // appears, and "All paid up" does not either while a month is due.
  await expect(page.locator('.owed-card-amount')).toHaveCount(0)
  await expect(page.locator('.owed-card-clear')).toHaveCount(0)

  // A parent settles it, after the transfer, with the PIN.
  await page.getByRole('button', { name: 'Parent' }).click()
  await page.getByRole('tab', { name: 'Savings' }).click()
  await expect(page.getByText('Ready to settle')).toBeVisible()
  await expect(page.getByText('paid into his bank account').first()).toBeVisible()
  await page.getByLabel('Bank balance after the transfer (optional)').fill('20.00')
  await page.getByRole('button', { name: 'Settle the match' }).click()
  const dialog = page.locator('.dialog-backdrop')
  await page.locator('#pin').fill('0000')
  await dialog.getByRole('button', { name: /^Settle at / }).click()
  await expect(dialog).toHaveCount(0)
  // The bank figure was checked against the books once the match was on them.
  await expect(page.locator('.reconciled-ok, .reconciled-off')).toBeVisible()

  await page.getByRole('button', { name: 'Back to the week' }).first().click()
  await page.locator('.total').waitFor()
  await expect(page.locator('.owed-interest')).toHaveCount(0)
  await expect(page.locator('.owed-card-clear')).toHaveText('All paid up')
})
