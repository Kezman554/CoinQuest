/**
 * The week fits the kitchen panel: 1280x800, a 10" touch screen.
 *
 * A layout fact, and only a rendered page can show it. The seed is too light
 * to test against — one chore a day — so the week is reshaped on its way to
 * the page into the heavy week the household actually has: three chores a day,
 * one with a long name, the chore money at risk, a make-good route showing,
 * the missed-chore notice beside it inside the money card, the missed chore
 * itself on Monday's tile with its "Not missed after all" button under it,
 * and two weeks owed. Every chore is reset to untouched, then one is set to
 * "Waiting to be checked" — the common state that wraps — so the result does
 * not depend on what earlier specs did to the scratch database. Nothing here
 * is computed by the browser; the figures are only made to be present, so the
 * space they take is real. A chore claimed and rejected ("Have another go",
 * "Not accepted last time") takes two lines more than this and is the days
 * region's to scroll.
 *
 * The fit is tight — a few pixels at the time of writing — which is the
 * reason this exists: a type-scale change that takes those pixels shows up
 * here rather than on the wall. A fourth chore is the backstop's case: the
 * page still does not scroll, and the days region does instead.
 */

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const EXTRA = ['Lunchbox / plates / cups by sink', 'Shoes and coat away', 'Teeth and wash']

async function heavyWeek(page: Page, choresPerDay: number) {
  await page.route('**/api/week/open', async (route) => {
    const response = await route.fetch()
    const week = await response.json()
    const fresh = { state: 'untouched', can_claim: true, rejection_count: 0, miss_origin: null }
    for (const day of week.days) {
      const seeded = day.chores[0]
      if (!seeded) continue
      Object.assign(seeded, fresh)
      day.chores.unshift({ ...seeded, instance_id: seeded.instance_id + 10000, name: EXTRA[0] })
      for (let i = 1; i < choresPerDay - 1; i++) {
        day.chores.push({ ...seeded, instance_id: seeded.instance_id + 10000 * (i + 1), name: EXTRA[i] })
      }
    }
    Object.assign(week.days[0].chores[1], { state: 'claimed', can_claim: false })
    const missed = week.days[1].chores[1]
    Object.assign(missed, { state: 'missed', can_claim: false, miss_origin: 'parent_marked' })
    week.recovery.needs = [{ definition_id: missed.definition_id, miss_name: 'Make bed', covered_by: null }]
    week.recovery.outstanding = 1
    week.recovery.options = [{ ...week.weekly[0].instances[0], name: 'Wash the car' }]
    week.recovery.urgent = false
    week.recovery.days_remaining = 3
    week.totals.chore_pay_awarded = false
    week.totals.chore_pay_at_stake_pence = 200
    week.totals.payable_total_pence = 100
    week.recovery.make_good = { names: ['Wash the car'], restores_to_pence: 300 }
    await route.fulfill({ response, json: week })
  })
  await page.route('**/api/weeks/owed/outstanding', (route) =>
    route.fulfill({
      json: [
        { week_id: 901, start_date: '2026-10-11', end_date: '2026-10-17', settled_total_pence: 300, reward_pence: 0, owed_pence: 300, is_paid: false },
        { week_id: 902, start_date: '2026-10-18', end_date: '2026-10-24', settled_total_pence: 250, reward_pence: 0, owed_pence: 250, is_paid: false },
      ],
    }),
  )
}

async function measure(page: Page) {
  await page.locator('.total-makegood').waitFor()
  return page.evaluate(() => {
    const days = document.querySelector('.wall-main') as HTMLElement
    return {
      pageScrolls: document.documentElement.scrollHeight > innerHeight,
      daysOverflow: days.scrollHeight - days.clientHeight,
    }
  })
}

test.describe('the week on the 1280x800 kitchen panel', () => {
  test.use({ viewport: { width: 1280, height: 800 } })

  test('a heavy week with a make-good showing fits without any scrolling', async ({ page }) => {
    await heavyWeek(page, 3)
    await page.goto('/')
    const fit = await measure(page)
    expect(fit.pageScrolls).toBe(false)
    expect(fit.daysOverflow).toBe(0)
    // The notice is in the money card, beside the make-good line, not a row
    // of its own above the week.
    await expect(page.locator('.total [role="status"]')).toContainText('You missed Make bed')
    await expect(page.locator('.total-route .total-makegood')).toBeVisible()
  })

  test('a heavier one scrolls the days, never the page', async ({ page }) => {
    await heavyWeek(page, 4)
    await page.goto('/')
    const fit = await measure(page)
    expect(fit.pageScrolls).toBe(false)
    expect(fit.daysOverflow).toBeGreaterThan(0)
    // The figure the child came to read is still where it was.
    await expect(page.locator('.total-amount')).toBeInViewport()
  })
})

test('on a phone nothing runs off either edge', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await heavyWeek(page, 3)
  await page.goto('/')
  await page.locator('.total-makegood').waitFor()
  const spilled = await page.evaluate(() =>
    [...document.querySelectorAll('body *')]
      .filter((e) => {
        const r = e.getBoundingClientRect()
        return r.right > innerWidth + 1 || r.left < -1
      })
      .map((e) => e.className),
  )
  expect(spilled).toEqual([])
})
