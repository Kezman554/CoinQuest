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
import type { Page } from '@playwright/test'

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

  test('Approve all, then Confirm, commits the whole batch through the preview and the PIN', async ({
    page,
    request,
  }) => {
    // Thursday's and Saturday's "Make bed", claimed for real: no other spec
    // reads those days, and the chore pays 0p, so the week's figure the wall
    // specs check is the same either way.
    const view = await (await request.post('/api/week/open')).json()
    for (const weekday of ['Thursday', 'Saturday']) {
      const day = view.days.find((d: { weekday: string }) => d.weekday === weekday)
      const bed = day.chores.find(
        (chore: { name: string; state: string }) =>
          chore.name === 'Make bed' && chore.state === 'untouched',
      )
      expect(bed, weekday).toBeTruthy()
      const claimed = await request.post('/api/claims', { data: { instance_id: bed.instance_id } })
      expect(claimed.ok(), weekday).toBe(true)
    }

    await page.goto('/')
    await page.getByText('E2E Kid').waitFor()
    await page.getByRole('button', { name: 'Parent' }).click()

    const items = page.locator('li.queue-item')
    await expect(items).toHaveCount(2)

    // Staging only: pressing it asks nothing of the server.
    const reviews = watchReviews(page)
    const approveAll = page.getByRole('button', { name: 'Approve all' })
    const before = await items.first().boundingBox()
    await approveAll.click()

    // Every row shows as chosen, by the same rulings the Yes buttons write.
    await expect(page.locator('li.queue-item.ruled-confirm')).toHaveCount(2)
    for (const yes of await items.locator('button.button-yes').all()) {
      await expect(yes).toHaveAttribute('aria-pressed', 'true')
    }
    // Nothing is left to stage: it stays in place, greyed, and says why —
    // and the queue under it has not moved.
    await expect(approveAll).toBeDisabled()
    await expect(approveAll).toHaveAccessibleDescription('Nothing left to approve.')
    expect(await items.first().boundingBox()).toEqual(before)
    await expect(page.locator('.batch-action')).toHaveText('Confirming 2 claims')
    expect(reviews).toEqual([])

    await page.locator('.batch').getByRole('button', { name: 'Confirm' }).click()

    // The preview, then the PIN, exactly as for a batch built a row at a time.
    const dialog = page.locator('.dialog-backdrop')
    await expect(dialog).toBeVisible()
    expect(reviews).toEqual(['/api/parent/review/preview'])
    await page.locator('#pin').fill('0000')
    await dialog.getByRole('button', { name: 'Confirm the batch' }).click()

    await expect(dialog).toHaveCount(0)
    await expect(items).toHaveCount(0)
    await expect(page.locator('.last-batch')).toHaveText('Confirmed 2 claims — by E2E Parent.')
    // An empty queue has nowhere for it to sit.
    await expect(approveAll).toHaveCount(0)

    await page.reload()
    await page.getByRole('button', { name: 'Parent' }).click()
    await expect(page.locator('li.queue-item')).toHaveCount(0)
  })

  test('a refused claim stays refused through Approve all, and every row can still change', async ({
    page,
  }) => {
    // On a phone: the button and its note wrap inside the panel.
    await page.setViewportSize({ width: 390, height: 844 })
    await threeClaimsWaiting(page)
    const reviews = watchReviews(page)
    await expectNoSideways(page)

    const items = page.locator('li.queue-item')
    await items.nth(1).locator('button.button-no').click()
    await expect(page.locator('.queue-tools-note')).toContainText('the 2 claims not yet ruled')

    await page.getByRole('button', { name: 'Approve all' }).click()

    await expect(items.nth(0)).toHaveClass(/ruled-confirm/)
    await expect(items.nth(1)).toHaveClass(/ruled-reject/)
    await expect(items.nth(1).locator('button.button-no')).toHaveAttribute('aria-pressed', 'true')
    await expect(items.nth(1).locator('button.button-yes')).toHaveAttribute('aria-pressed', 'false')
    await expect(items.nth(2)).toHaveClass(/ruled-confirm/)
    await expect(page.locator('.batch-action')).toHaveText(
      'Confirming 2 claims and refusing 1 claim',
    )

    // Every row ruled: Approve all greys rather than going.
    await expect(page.getByRole('button', { name: 'Approve all' })).toBeDisabled()

    // Switched with its own button, and cleared with its own button: the
    // cleared row is unruled again, so Approve all is enabled once more.
    await items.nth(0).locator('button.button-no').click()
    await expect(items.nth(0)).toHaveClass(/ruled-reject/)
    await items.nth(2).locator('button.button-yes').click()
    await expect(items.nth(2)).toHaveClass(/ruled-none/)
    await expect(page.locator('.batch-action')).toHaveText('refusing 2 claims')
    await expect(page.getByRole('button', { name: 'Approve all' })).toBeEnabled()

    expect(reviews).toEqual([])
  })

  test('leaving the screen after Approve all commits nothing', async ({ page }) => {
    // On the kitchen panel.
    await page.setViewportSize({ width: 1280, height: 800 })
    await threeClaimsWaiting(page)
    const reviews = watchReviews(page)
    await expectNoSideways(page)

    await page.getByRole('button', { name: 'Approve all' }).click()
    await expect(page.locator('li.queue-item.ruled-confirm')).toHaveCount(3)

    await page.getByRole('button', { name: 'Back to the week' }).first().click()
    await page.getByText('E2E Kid').waitFor()
    await page.getByRole('button', { name: 'Parent' }).click()

    // Back on the queue: every claim still waiting, none of them ruled, and
    // nothing was ever previewed or applied.
    await expect(page.locator('li.queue-item')).toHaveCount(3)
    await expect(page.locator('li.queue-item.ruled-none')).toHaveCount(3)
    await expect(page.getByRole('button', { name: 'Approve all' })).toBeEnabled()
    expect(reviews).toEqual([])
  })
})

async function expectNoSideways(page: Page) {
  await expect(page.getByRole('button', { name: 'Approve all' })).toBeInViewport()
  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }))
  expect(scrollWidth).toBeLessThanOrEqual(clientWidth)
}

/** Every request to a review route — the preview and the commit — as made. */
function watchReviews(page: Page): string[] {
  const seen: string[] = []
  page.on('request', (req) => {
    const path = new URL(req.url()).pathname
    if (path.includes('/review')) seen.push(path)
  })
  return seen
}

/** Three claims in the queue that the server never holds, so a spec that
 *  only stages can prove it sent nothing without spending a real chore. */
async function threeClaimsWaiting(page: Page) {
  const claim = (instance_id: number, due_date: string) => ({
    instance_id,
    definition_id: 1,
    name: 'Make bed',
    category: 'basic',
    cadence: 'daily',
    amount_pence: 0,
    sequence: 1,
    due_date,
    week_id: 1,
    week_start_date: '2026-10-26',
    week_end_date: '2026-11-01',
    claimed_at: new Date().toISOString(),
    rejection_count: 0,
  })
  await page.route('**/api/parent/queue', (route) =>
    route.fulfill({
      json: [claim(99991, '2026-10-26'), claim(99992, '2026-10-27'), claim(99993, '2026-10-28')],
    }),
  )
  await page.goto('/')
  await page.getByText('E2E Kid').waitFor()
  await page.getByRole('button', { name: 'Parent' }).click()
  await expect(page.locator('li.queue-item')).toHaveCount(3)
}
