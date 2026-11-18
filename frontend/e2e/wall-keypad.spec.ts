/**
 * The keypad at the wall, and nowhere else (Session AS; docs/wall-inputs.md).
 *
 * The wall is told apart by being framed by a page on the loopback address —
 * the hub dashboard at http://localhost:8500 framing CoinQuest. Here a small
 * real server on http://localhost:8599, started by this file, frames the
 * real app the same way, in a 1280×800 touch context; every tap goes to the
 * real backend. It has to be a real server: a page Playwright fakes has no
 * address, counts as public, and Chromium's local-network checks then refuse
 * to let it frame a loopback app at all. The laptop is the app opened directly, and the phone the same on
 * an emulated phone.
 */

import { createServer } from 'node:http'
import type { Server } from 'node:http'

import { expect, test } from '@playwright/test'
import type { Browser, FrameLocator, Page } from '@playwright/test'
import { devices } from '@playwright/test'

import { BASE_URL } from './paths.mjs'

const DASHBOARD = 'http://localhost:8599/'

let dashboard: Server

test.beforeAll(async () => {
  dashboard = createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/html' })
    response.end(`<!doctype html><body style="margin:0"><iframe src="${BASE_URL}/"
      style="border:0;width:1280px;height:800px;display:block"></iframe></body>`)
  })
  await new Promise<void>((resolve) => dashboard.listen(8599, 'localhost', resolve))
})

test.afterAll(async () => {
  await new Promise((resolve) => dashboard.close(resolve))
})

/** The wall: CoinQuest in an iframe on a loopback page, touch, 1280×800. */
async function wall(browser: Browser): Promise<{ page: Page; app: FrameLocator }> {
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 },
    hasTouch: true,
  })
  const page = await context.newPage()
  await page.goto(DASHBOARD)
  const app = page.frameLocator('iframe')
  await app.getByText('E2E Kid').first().waitFor()
  return { page, app }
}

async function tapKeys(app: FrameLocator, keys: string[]) {
  const pad = app.getByRole('group', { name: 'Keypad' })
  for (const key of keys) {
    const name = key === '.' ? 'Point' : key === 'Delete' ? 'Delete the last digit' : key
    await pad.getByRole('button', { name, exact: true }).tap()
  }
}

test.describe('at the wall', () => {
  test('an amount by keypad and a tapped reason, then a PIN by keypad, go through', async ({
    browser,
  }) => {
    const { page, app } = await wall(browser)

    // The child's own form: the amount by keypad, where it came from tapped.
    await app.getByRole('button', { name: 'Savings', exact: true }).tap()
    const amount = app.getByPlaceholder('Amount, e.g. £5')
    await expect(amount).toHaveAttribute('inputmode', 'none')
    await amount.tap()
    await expect(app.getByRole('group', { name: 'Keypad' })).toBeVisible()
    // A third decimal and a second point are refused; Delete takes one back.
    await tapKeys(app, ['2', '.', '5', '0', '0', '.', '7', 'Delete'])
    await expect(amount).toHaveValue('2.5')
    await tapKeys(app, ['0'])
    await expect(amount).toHaveValue('2.50')

    // Typing is not offered here: the words are tapped.
    const sources = app.getByRole('group', { name: 'Where it came from' })
    await expect(app.getByPlaceholder('Where it came from')).toHaveCount(0)
    await sources.getByRole('button', { name: 'Birthday' }).tap()
    await expect(sources.getByRole('button', { name: 'Birthday' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    // The keypad closed when something else was tapped.
    await expect(app.getByRole('group', { name: 'Keypad' })).toHaveCount(0)

    await app.getByRole('button', { name: 'Add it' }).tap()
    await expect(app.locator('.deposit-pending')).toContainText('£2.50 — Birthday')

    // A parent confirms it with the PIN, by keypad, beside the field.
    await app.getByRole('button', { name: 'Back to the week' }).first().tap()
    await app.getByRole('button', { name: 'Parent', exact: true }).tap()
    await app.getByRole('tab', { name: /^Savings/ }).tap()
    const waiting = app.locator('.deposit-pending li', { hasText: '£2.50 — Birthday' })
    await waiting.getByRole('button', { name: 'Confirm' }).tap()

    const dialog = app.locator('.dialog')
    const pin = dialog.locator('#pin')
    await expect(pin).toHaveAttribute('inputmode', 'none')
    await expect(pin).toHaveAttribute('type', 'password')
    // Wrong digits, cleared; then three by keypad and the last from a
    // physical keyboard, which still types at the wall.
    await tapKeys(app, ['9', '9'])
    await dialog.getByRole('button', { name: 'Clear' }).tap()
    await expect(pin).toHaveValue('')
    await tapKeys(app, ['0', '0', '0'])
    await pin.press('0')
    await expect(pin).toHaveValue('0000')

    // The dialog, keypad and all, fits the panel: its button is on screen.
    const confirm = dialog.getByRole('button', { name: 'Confirm', exact: true })
    await expect(confirm).toBeInViewport()
    await confirm.tap()
    await expect(dialog).toHaveCount(0)
    await expect(app.locator('.deposit-pending li', { hasText: '£2.50 — Birthday' })).toHaveCount(0)

    await page.context().close()
  })

  test('text fields stay in place, disabled, and say to use the laptop or a phone', async ({
    browser,
  }) => {
    const { page, app } = await wall(browser)
    await app.getByRole('button', { name: 'Parent', exact: true }).tap()

    // An optional reason is disabled with its own line; the waiver still works.
    const dayWhy = app.getByPlaceholder("Why (e.g. away at Grandma's)").first()
    await expect(dayWhy).toBeDisabled()
    await expect(dayWhy).toHaveAccessibleDescription('Use the laptop or a phone to type here.')
    await expect(app.getByText('Use the laptop or a phone to type here.').first()).toBeVisible()

    // A reward needs words: its amount and its words are disabled, one reason.
    await app.getByRole('tab', { name: /^Chores/ }).tap()
    const reward = app.locator('section', { has: app.getByRole('heading', { name: 'Record a reward' }) })
    await expect(reward.getByPlaceholder('Amount, e.g. £2.50')).toBeDisabled()
    await expect(reward.getByPlaceholder('What it is for')).toBeDisabled()
    await expect(reward.getByPlaceholder('What it is for')).toHaveAccessibleDescription(
      'Use the laptop or a phone.',
    )

    // A new chore needs a typed name: the whole form waits for the laptop.
    await app.getByRole('button', { name: 'Add a chore' }).tap()
    await expect(app.getByPlaceholder('Name')).toBeDisabled()
    await expect(app.getByPlaceholder('Name')).toHaveAccessibleDescription(
      'Use the laptop or a phone.',
    )

    await page.context().close()
  })
})

test('on the laptop nothing changes: no keypad, and typing goes through', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/')
  await page.getByText('E2E Kid').first().waitFor()
  await page.getByRole('button', { name: 'Savings', exact: true }).click()

  const amount = page.getByPlaceholder('Amount, e.g. £5')
  await expect(amount).toHaveAttribute('inputmode', 'decimal')
  await amount.click()
  await amount.fill('1.25')
  await expect(page.getByRole('group', { name: 'Keypad' })).toHaveCount(0)
  await page.getByPlaceholder('Where it came from').fill('Typed on the laptop')
  await page.getByRole('button', { name: 'Add it' }).click()
  await expect(page.locator('.deposit-pending')).toContainText('£1.25 — Typed on the laptop')

  // Declined with a typed PIN: the dialog has no keypad either.
  await page.getByRole('button', { name: 'Back to the week' }).first().click()
  await page.getByRole('button', { name: 'Parent', exact: true }).click()
  await page.getByRole('tab', { name: /^Savings/ }).click()
  await page
    .locator('.deposit-pending li', { hasText: 'Typed on the laptop' })
    .getByRole('button', { name: 'Decline' })
    .click()
  const pin = page.locator('#pin')
  await expect(pin).toHaveAttribute('inputmode', 'numeric')
  await expect(page.getByRole('group', { name: 'Keypad' })).toHaveCount(0)
  await pin.fill('0000')
  await page.locator('.dialog').getByRole('button', { name: 'Decline' }).click()
  await expect(page.locator('.dialog')).toHaveCount(0)
  await expect(page.locator('.deposit-pending li', { hasText: 'Typed on the laptop' })).toHaveCount(0)

  // And text is typed here as ever.
  await page.getByRole('tab', { name: /^Chores/ }).click()
  await expect(page.getByPlaceholder('What it is for')).toBeEnabled()
})

test('on a phone, its own keyboard and never the keypad', async ({ browser }) => {
  const context = await browser.newContext({ ...devices['Pixel 5'] })
  const page = await context.newPage()
  await page.goto(`${BASE_URL}/`)
  await page.getByText('E2E Kid').first().waitFor()
  await page.getByRole('button', { name: 'Savings', exact: true }).tap()
  const amount = page.getByPlaceholder('Amount, e.g. £5')
  await amount.tap()
  await expect(amount).toHaveAttribute('inputmode', 'decimal')
  await expect(page.getByRole('group', { name: 'Keypad' })).toHaveCount(0)
  await expect(page.getByPlaceholder('Where it came from')).toBeEnabled()
  await context.close()
})

test('at the wall, a claim batch with its consequences fits the panel, PIN keys and all', async ({
  browser,
}) => {
  // Two claims in the queue the server never holds, and the consequence the
  // preview would give, so the dialog is as full as a real batch makes it.
  // Nothing is submitted: the check is that Confirm is on the panel.
  const { page, app } = await wall(browser)
  const claim = (instance_id: number) => ({
    instance_id,
    definition_id: 1,
    name: 'Make bed',
    category: 'basic',
    cadence: 'daily',
    amount_pence: 0,
    sequence: 1,
    due_date: '2026-10-26',
    week_id: 1,
    week_start_date: '2026-10-26',
    week_end_date: '2026-11-01',
    claimed_at: new Date().toISOString(),
    rejection_count: 0,
  })
  const figures = (total: number, awarded: boolean) => ({
    total_pence: total,
    misses: 1,
    bonus_pence: 0,
    reward_pence: 0,
    chore_pay_pence: 200,
    chore_pay_awarded: awarded,
    chore_pay_at_stake_pence: 200,
    misses_outstanding: awarded ? 0 : 1,
    recoveries: [],
  })
  await page.route('**/api/parent/queue', (route) => route.fulfill({ json: [claim(99981), claim(99982)] }))
  await page.route('**/api/parent/review/preview', (route) =>
    route.fulfill({
      json: [
        {
          week_id: 1,
          start_date: '2026-10-26',
          end_date: '2026-11-01',
          confirmed: 2,
          rejected: 0,
          before: figures(100, false),
          after: figures(300, true),
          difference_pence: 200,
          rescues_the_chore_pay: true,
          loses_the_chore_pay: false,
        },
      ],
    }),
  )
  await app.getByRole('button', { name: 'Parent', exact: true }).tap()
  await app.getByRole('button', { name: 'Approve all' }).tap()
  await app.locator('.batch').getByRole('button', { name: 'Confirm' }).tap()

  const dialog = app.locator('.dialog')
  await expect(dialog.getByRole('group', { name: 'Keypad' })).toBeVisible()
  await expect(dialog.getByRole('button', { name: 'Confirm the batch' })).toBeInViewport({ ratio: 1 })
  const fits = await dialog.evaluate((element) => element.scrollHeight <= element.clientHeight)
  expect(fits).toBe(true)
  await page.context().close()
})
