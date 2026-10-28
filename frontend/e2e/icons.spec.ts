/**
 * Every icon path is served as the icon, not as index.html.
 *
 * An unknown path falls back to index.html with a 200 (app/frontend.py), so
 * a missing icon never shows as a 404 — the browser just gets a page where
 * it wanted a picture, and keeps whatever icon it had before. /favicon.ico
 * is asked for by browsers that never read the page's links.
 */

import { expect, test } from '@playwright/test'

const ICONS: [string, string][] = [
  ['/favicon.ico', 'image/'],
  ['/favicon.svg', 'image/svg+xml'],
  ['/favicon-16.png', 'image/png'],
  ['/favicon-32.png', 'image/png'],
  ['/apple-touch-icon.png', 'image/png'],
]

for (const [path, type] of ICONS) {
  test(`${path} is served as an image`, async ({ request }) => {
    const response = await request.get(path)
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toContain(type)
  })
}

test('/favicon.ico is an ICO holding the 16 and 32 px coins', async ({ request }) => {
  const body = await (await request.get('/favicon.ico')).body()
  expect([...body.subarray(0, 6)]).toEqual([0, 0, 1, 0, 2, 0])
  expect([body[6], body[22]]).toEqual([16, 32])
})
