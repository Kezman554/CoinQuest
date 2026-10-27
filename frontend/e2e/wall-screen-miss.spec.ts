/**
 * A miss on the wall screen, and taking it back (Session Y).
 *
 * Marking a miss used to be a button on every day tile. It now lives on the
 * parent screen only, so this marks it with the same uncredentialed call the
 * parent screen makes and then reads the wall: the tiles must not offer the
 * mark, the figure has to move, the way back has to appear beside the number
 * it restores, and the undo has to be the one thing on the child's screen
 * that stops and asks for the PIN. Every one of those is a fact about the
 * rendered page.
 *
 * The figures are the card's own worked example, against the seeded scheme:
 * £1 base plus a £2 basic pot. One marked miss takes the whole pot — chore pay
 * is all or nothing — so a clean week goes £3 to £1, and clearing the mark
 * brings it back. Nothing here is computed by the browser; every figure comes
 * back from the engine's own proposal on the reload each act triggers.
 */

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

/** Mark Wednesday's "Make bed" missed the way the parent screen does — no PIN
 *  — and reload so the wall reads the new state. */
async function markWednesdayBedMissed(page: Page) {
  const week = await (await page.request.post('/api/week/open')).json()
  const wednesday = week.days.find((day: { weekday: string }) => day.weekday === 'Wednesday')
  const bed = wednesday.chores.find((chore: { name: string }) => chore.name === 'Make bed')
  const marked = await page.request.post(`/api/instances/${bed.instance_id}/missed`, {
    data: { instance_id: bed.instance_id },
  })
  expect(marked.ok()).toBe(true)
  await page.reload()
}

test.describe('a missed chore on the day tiles', () => {
  test('marking a Wednesday chore missed drops the figure, and the PIN puts it back', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByText('E2E Kid').waitFor()

    const total = page.locator('.total-amount')
    await expect(total).toHaveText('£3')

    // The tiles offer no way to mark a miss — that is the parent screen's.
    await expect(page.getByRole('button', { name: 'Missed', exact: true })).toHaveCount(0)

    // Wednesday: untouched in the seed. Once marked, the whole chore pot is
    // gone, leaving the base, and nothing is subtracted here.
    await markWednesdayBedMissed(page)
    await expect(total).toHaveText('£1')
    const wednesday = page.locator('.day', { hasText: 'Wednesday' })
    const bed = wednesday.locator('.chore', { hasText: 'Make bed' })

    // The way back, in the notice in the money card beside the number it
    // restores, drawn from the same proposal that produced the number. With
    // the notice showing there is no separate make-good box.
    const notice = page.locator('.total [role="status"]')
    await expect(notice).toContainText('Wash the car')
    await expect(notice).toContainText('that takes this week back to £3')
    await expect(page.locator('.total-makegood')).toHaveCount(0)

    // The tile now reads as missed, and carries the undo inside it rather
    // than a claim.
    await expect(bed).toHaveClass(/chore-missed/)

    // And this is the direction that asks.
    await bed.getByRole('button', { name: 'Not missed after all' }).click()
    const dialog = page.locator('.dialog-backdrop')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('Make bed')

    await page.locator('#pin').fill('0000')
    await dialog.getByRole('button', { name: 'Clear the miss' }).click()

    await expect(dialog).toHaveCount(0)
    await expect(total).toHaveText('£3')
    await expect(page.locator('.total [role="status"]')).toHaveCount(0)
    await expect(page.locator('.total-makegood')).toHaveCount(0)

    // It survives a real reload: the state is the database's, not the page's.
    await page.reload()
    await expect(page.locator('.total-amount')).toHaveText('£3')
  })

  test('a wrong PIN refuses the undo, and the miss stays where it was', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByText('E2E Kid').waitFor()

    await markWednesdayBedMissed(page)
    await expect(page.locator('.total-amount')).toHaveText('£1')
    const wednesday = page.locator('.day', { hasText: 'Wednesday' })
    const bed = wednesday.locator('.chore', { hasText: 'Make bed' })

    await bed.getByRole('button', { name: 'Not missed after all' }).click()
    const dialog = page.locator('.dialog-backdrop')
    await page.locator('#pin').fill('9999')
    await dialog.getByRole('button', { name: 'Clear the miss' }).click()

    // Refused server-side, said on the screen, and nothing given back.
    await expect(dialog.locator('.dialog-error')).toBeVisible()
    await page.getByRole('button', { name: 'Cancel' }).click()
    await expect(page.locator('.total-amount')).toHaveText('£1')
  })
})
