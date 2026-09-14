/**
 * The `test` every spec imports.
 *
 * It adds two things to Playwright's own: the skip when the stack is not
 * there, and `ask`, which sends one question and waits for the turn to
 * finish — every spec needs an answered turn before it can assert on
 * anything downstream of one.
 */

import { expect, test as base, type Page } from '@playwright/test'

export const test = base.extend<{ app: Page }>({
  app: async ({ page }, use, testInfo) => {
    test.skip(process.env.E2E_READY !== 'true',
              'the graph is not loaded; run srd-graph-load')

    // Whatever the browser complained about, kept with the failure. A blank
    // page is otherwise indistinguishable from a slow one from out here.
    const noise: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') noise.push(`console: ${message.text()}`)
    })
    page.on('pageerror', (error) => noise.push(`page error: ${error.message}`))
    page.on('requestfailed', (request) =>
      noise.push(`request failed: ${request.url()}`
                 + ` (${request.failure()?.errorText})`))

    await page.goto('/')
    // The shell, before anything asks it a question: a test that fails here
    // failed to load the application, which is worth saying plainly rather
    // than as a timeout on whatever it tried to click first.
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
 * Ask one question and wait for the answer to be complete.
 *
 * "Complete" is the citations arriving, not the first token: they are
 * resolved once the answer is finished, so a chip on screen is the turn's
 * own done marker.
 */
export async function ask(page: Page, question: string) {
  await page.getByPlaceholder('Ask a rules question…').fill(question)
  await page.keyboard.press('Enter')
  await expect(page.locator('.citations .chip').first())
    .toBeVisible({ timeout: 30_000 })
}

/** The panel, whichever tab it is showing. */
export const panel = (page: Page) => page.locator('aside.panel')
