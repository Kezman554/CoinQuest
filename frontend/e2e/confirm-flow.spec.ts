/**
 * The parent's confirm/reject flow, driven end to end (Session T).
 *
 * Everything below exercises the real app in a real browser — the same
 * gap that let the actual defect through, since every unit test of
 * POST /api/claims/review calls the endpoint directly and never renders
 * the screen a parent stages a batch on. If the "Confirm" button in the
 * Claims Waiting section moves back behind a hidden intermediate step, is
 * renamed, or the click handler stops calling onSubmit, the selectors and
 * assertions below fail — that is what makes this a regression test for
 * the actual failure rather than a demonstration that it once worked.
 */

import { expect, test } from '@playwright/test'

test.describe('confirming and rejecting claims from the parent queue', () => {
  test('a mixed batch — confirm one, reject another — commits, is refused nothing, and needs no manual reload', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByText('E2E Kid').waitFor()

    await page.getByRole('button', { name: 'Parent' }).click()
    await expect(page.getByText('Claims waiting')).toBeVisible()

    // Seeded by global-setup.ts: a pending claim in the current week and one
    // left over from the previous week — the mix the card's test plan asked
    // for. Ordered oldest-claimed-first by the API; both were claimed at the
    // same instant in the seed, so the tie breaks on insertion order —
    // current week first (instance id 1), previous week second (id 3).
    const items = page.locator('li.queue-item')
    await expect(items).toHaveCount(2)

    const currentWeekItem = items.nth(0)
    const previousWeekItem = items.nth(1)

    // Stage: confirm the previous week's leftover claim, reject the current
    // week's one. One batch, two weeks, both decisions.
    await previousWeekItem.locator('button.button-yes').click()
    await currentWeekItem.locator('button.button-no').click()

    // The commit affordance is reachable the moment something is staged —
    // no separate, differently-labelled button has to be found first. This
    // is the exact defect: the button existed, but not here, not yet.
    const confirmButton = page.locator('.batch').getByRole('button', { name: 'Confirm' })
    await expect(confirmButton).toBeVisible()
    await confirmButton.click()

    // The impact readback still comes before the commit — it has just
    // moved into the dialog that authorises it, the same place every other
    // act on this screen already shows its consequence.
    const dialog = page.locator('.dialog-backdrop')
    await expect(dialog).toBeVisible()
    await expect(dialog).toContainText(/miss/i)

    await page.locator('#pin').fill('0000')
    await dialog.getByRole('button', { name: 'Confirm the batch' }).click()

    // Committed, and reflected immediately — no reload needed to see it.
    await expect(dialog).toHaveCount(0)
    await expect(items).toHaveCount(0)

    // And it actually persisted, not merely an optimistic UI update.
    await page.reload()
    await page.getByRole('button', { name: 'Parent' }).click()
    await expect(page.locator('li.queue-item')).toHaveCount(0)
  })

  test('a batch refused server-side is surfaced, not committed and not swallowed', async ({
    page,
    request,
  }) => {
    // A fresh claim of its own, independent of the other test: open the
    // week (idempotent — never touches what already exists) and claim
    // whatever instance came up untouched.
    const view = await (await request.post('/api/week/open')).json()
    const untouched = view.days
      .flatMap((day: { chores: { instance_id: number | null; state: string }[] }) => day.chores)
      .find((chore: { instance_id: number | null; state: string }) => chore.state === 'untouched')
    expect(untouched).toBeTruthy()
    const claimed = await (
      await request.post('/api/claims', { data: { instance_id: untouched.instance_id } })
    ).json()

    await page.goto('/')
    await page.getByText('E2E Kid').waitFor()
    await page.getByRole('button', { name: 'Parent' }).click()
    await expect(page.getByText('Claims waiting')).toBeVisible()

    const staged = page
      .locator('li.queue-item')
      .filter({ has: page.locator('button.button-yes') })
      .first()
    await staged.locator('button.button-yes').click()

    // Someone else confirms the very same instance in the meantime — a
    // second device, or a parent who moved faster. The batch about to be
    // submitted is now stale.
    const raced = await request.post('/api/claims/review', {
      data: { pin: '0000', decisions: [{ instance_id: claimed.id, decision: 'confirm' }] },
    })
    expect(raced.ok()).toBe(true)

    await page.locator('.batch').getByRole('button', { name: 'Confirm' }).click()

    // Refused, and it looks refused: no PIN dialog opens on a batch that
    // was never going to apply, and the reason is on the screen, not in a
    // console nobody in the kitchen is reading.
    await expect(page.locator('.dialog-backdrop')).toHaveCount(0)
    const problem = page.locator('.batch .dialog-error[role="alert"]')
    await expect(problem).toBeVisible()
    await expect(problem).toContainText('not a pending claim')
  })
})
