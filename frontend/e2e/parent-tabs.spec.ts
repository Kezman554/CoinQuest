/**
 * The parent screen's three tabs.
 *
 * Each tab shows its own sections and none of the others', and the weekly
 * work is what the screen opens on — the queue confirm-flow.spec.ts drives
 * has to be there without a tap. Counts on the tabs depend on what the other
 * specs have already done to the seeded queue, so nothing here asserts one.
 */

import { expect, test } from '@playwright/test'

test('the parent screen splits into This week, Chores and Savings', async ({ page }) => {
  await page.goto('/')
  await page.getByText('E2E Kid').waitFor()
  await page.getByRole('button', { name: 'Parent' }).click()

  const heading = (name: string) => page.getByRole('heading', { name, exact: false })
  const tab = (name: string) => page.getByRole('tab', { name, exact: false })

  // Opens on the weekly work.
  await expect(tab('This week')).toHaveAttribute('aria-selected', 'true')
  await expect(heading('Claims waiting')).toBeVisible()
  await expect(heading('Owed')).toBeVisible()
  await expect(heading('Chores')).toHaveCount(0)
  await expect(heading('Savings match')).toHaveCount(0)

  await tab('Chores').click()
  await expect(tab('Chores')).toHaveAttribute('aria-selected', 'true')
  await expect(heading('Chores')).toBeVisible()
  await expect(heading('Record a reward')).toBeVisible()
  await expect(heading('Claims waiting')).toHaveCount(0)

  // The arrow keys move along the tab list.
  await page.keyboard.press('ArrowRight')
  await expect(tab('Savings')).toHaveAttribute('aria-selected', 'true')
  await expect(tab('Savings')).toBeFocused()
  await expect(heading('Savings match')).toBeVisible()
  await expect(heading('Record a reward')).toHaveCount(0)

  await tab('This week').click()
  await expect(heading('Claims waiting')).toBeVisible()
})
