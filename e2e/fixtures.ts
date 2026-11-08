/**
 * Playwright's `test`, plus a skip when the stack is unavailable and an `ask`
 * fixture.
 */

import { expect, test as base, type Page } from '@playwright/test'

export const test = base.extend<{ app: Page }>({
  app: async ({ page }, use, testInfo) => {
    test.skip(process.env.E2E_READY !== 'true',
              'the graph is not loaded; run srd-graph-load')

    // Attach console errors to failures; a blank page otherwise looks slow.
    const noise: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') noise.push(`console: ${message.text()}`)
    })
    page.on('pageerror', (error) => noise.push(`page error: ${error.message}`))
    page.on('requestfailed', (request) =>
      noise.push(`request failed: ${request.url()}`
                 + ` (${request.failure()?.errorText})`))

    await page.goto('/')
    // Fail here, clearly, if the app did not load at all.
    await expect(page.getByPlaceholder('Ask a rules question…'))
      .toBeVisible({ timeout: 30_000 })

    await use(page)

    if (noise.length && testInfo.status !== testInfo.expectedStatus) {
      await testInfo.attach('browser', { body: noise.join('\n') })
    }
  },
})

export { expect }

/**
 * Ask a question and wait until its citations render, which marks the end of
 * the turn.
 */
export async function ask(page: Page, question: string) {
  await page.getByPlaceholder('Ask a rules question…').fill(question)
  await page.keyboard.press('Enter')
  await expect(page.locator('.citations .chip').first())
    .toBeVisible({ timeout: 30_000 })
}

/** The side panel, whichever tab is showing. */
export const panel = (page: Page) => page.locator('aside.panel')
