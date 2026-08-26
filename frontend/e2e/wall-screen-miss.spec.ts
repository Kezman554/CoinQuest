/**
 * Marking a miss from the wall screen, and taking it back (Session Y).
 *
 * This is the flow the whole session is about, and it is the kind that a unit
 * test calling the endpoint cannot catch: the control has to be *on the day
 * tile*, the figure has to move without a reload, the way back has to appear
 * beside the number it restores, and the undo has to be the one thing on the
 * child's screen that stops and asks for the PIN. Every one of those is a fact
 * about the rendered page.
 *
 * The figures are the card's own worked example, against the seeded scheme:
 * £1 base plus a £2 basic pot. One marked miss takes the whole pot — chore pay
 * is all or nothing — so a clean week goes £3 to £1, and clearing the mark
 * brings it back. Nothing here is computed by the browser; every figure comes
 * back from the engine's own proposal on the reload each act triggers.
 */

import { expect, test } from '@playwright/test'

test.describe('the missed control on the day tiles', () => {
  test('marking a Wednesday chore missed drops the figure, and the PIN puts it back', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByText('E2E Kid').waitFor()

    const total = page.locator('.total-amount')
    await expect(total).toHaveText('£3')

    // Wednesday: untouched in the seed, so it carries the missed control.
    const wednesday = page.locator('.day', { hasText: 'Wednesday' })
    const bed = wednesday.locator('.chore-row', { hasText: 'Make bed' })
    await bed.getByRole('button', { name: 'Missed', exact: true }).click()

    // No PIN, no dialog, and the figure has moved — the whole chore pot is
    // gone, leaving the base, with no reload and nothing subtracted here.
    await expect(page.locator('.dialog-backdrop')).toHaveCount(0)
    await expect(total).toHaveText('£1')

    // The way back, beside the number it restores, drawn from the same
    // proposal that produced the number.
    const makeGood = page.locator('.total-makegood')
    await expect(makeGood).toContainText('Wash the car')
    await expect(makeGood).toContainText('£3')

    // The tile now reads as missed, and carries the undo rather than a claim.
    await expect(bed.locator('.chore-missed')).toBeVisible()

    // And this is the direction that asks.
    await bed.getByRole('button', { name: 'Not missed after all' }).click()
    const dialog = page.locator('.dialog-backdrop')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText('Make bed')

    await page.locator('#pin').fill('0000')
    await dialog.getByRole('button', { name: 'Clear the miss' }).click()

    await expect(dialog).toHaveCount(0)
    await expect(total).toHaveText('£3')
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

    const wednesday = page.locator('.day', { hasText: 'Wednesday' })
    const bed = wednesday.locator('.chore-row', { hasText: 'Make bed' })
    await bed.getByRole('button', { name: 'Missed', exact: true }).click()
    await expect(page.locator('.total-amount')).toHaveText('£1')

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
