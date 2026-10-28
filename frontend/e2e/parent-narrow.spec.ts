/**
 * The parent view on a phone, and its disabled controls (DESIGN.md).
 *
 * At 390 wide no tab may scroll sideways: the closing row's "Void the week"
 * once reached 409px, because the reason and the button refused to wrap.
 * And a control the state forbids keeps its place and says why, rather than
 * vanishing — Confirm before anything is ruled is the case every parent
 * meets first.
 */

import { expect, test } from '@playwright/test'

test('no parent tab scrolls sideways at 390 wide', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Parent', exact: true }).click()

  for (const tab of [/^This week/, /^Chores/, /^Savings/]) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.getByRole('tabpanel')).toBeVisible()
    const { scrollWidth, clientWidth } = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }))
    expect(scrollWidth, `${tab}`).toBeLessThanOrEqual(clientWidth)
  }
})

test('Confirm stays in place, disabled, and says why until a claim is ruled', async ({
  page,
}) => {
  // One claim in the queue whatever earlier specs left there, without
  // claiming anything real: the specs after this one count on the seed.
  // Nothing here is submitted, so nothing reaches the server.
  await page.route('**/api/parent/queue', (route) =>
    route.fulfill({
      json: [
        {
          instance_id: 99999,
          definition_id: 1,
          name: 'Make bed',
          category: 'basic',
          cadence: 'daily',
          amount_pence: 0,
          sequence: 1,
          due_date: '2026-10-26',
          week_id: 1,
          week_start_date: '2026-10-25',
          week_end_date: '2026-10-31',
          claimed_at: new Date().toISOString(),
          rejection_count: 0,
        },
      ],
    }),
  )

  await page.goto('/')
  await page.getByRole('button', { name: 'Parent', exact: true }).click()

  const confirm = page.getByRole('button', { name: 'Confirm', exact: true })
  await expect(confirm).toBeDisabled()
  await expect(confirm).toHaveAccessibleDescription('Rule on a claim to build a batch.')

  // Ruling one makes it usable; the ruling is pressed, not only coloured.
  const yes = page.getByRole('button', { name: 'Yes', exact: true }).first()
  await yes.click()
  await expect(yes).toHaveAttribute('aria-pressed', 'true')
  await expect(confirm).toBeEnabled()

  // Undo the ruling, so later specs find the queue as seeded.
  await yes.click()
  await expect(confirm).toBeDisabled()
})
