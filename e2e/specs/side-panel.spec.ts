import type { Page } from '@playwright/test'

import { ask, expect, panel, test } from '../fixtures'

/** Open the first citation of an answered question. */
async function citation(page: Page) {
  await ask(page, 'What does the Prone condition do?')
  await page.locator('.citations .chip').first().click()
  await expect(panel(page)).toBeVisible()
}

/**
 * Wait for the page to finish rendering.  The canvas exists at placeholder
 * size from the start; the text layer's first span appears only after the
 * scale is final.
 */
async function rendered(page: Page) {
  await expect(page.locator('.pdf-page canvas').first())
    .toBeVisible({ timeout: 30_000 })
  await expect(page.locator('.textLayer span').first())
    .toBeAttached({ timeout: 30_000 })
}

test.describe('the page panel', () => {
  test('given a citation, when opened, then the book itself is rendered',
       async ({ app }) => {
    // Given a cited passage
    await citation(app)

    // When the panel draws it
    await rendered(app)

    // Then it is a rendered page of the PDF, captioned with its number
    await expect(app.locator('.pdf-page figcaption').first())
      .toHaveText(/^p\. \d+$/)
  })

  test('given a rendered page, when the citation is marked, then boxes are drawn',
       async ({ app }) => {
    // Given a cited passage on its page
    await citation(app)
    await rendered(app)

    // When the highlight boxes are counted
    const boxes = app.locator('.pdf-boxes span')

    // Then the passage is marked, line by line rather than as one block
    await expect(boxes.first()).toBeVisible()
    expect(await boxes.count()).toBeGreaterThan(1)
  })

  test('given a box, when measured, then it sits over the page it marks',
       async ({ app }) => {
    // Given a drawn page and its boxes
    await citation(app)
    await rendered(app)
    const page_ = await app.locator('.pdf-page canvas').first().boundingBox()
    const box = await app.locator('.pdf-boxes span').first().boundingBox()

    // When the two rectangles are compared
    // Then the highlight is inside the page, and is a line rather than a slab
    expect(box!.x).toBeGreaterThanOrEqual(page_!.x - 2)
    expect(box!.x + box!.width).toBeLessThanOrEqual(page_!.x + page_!.width + 2)
    expect(box!.height).toBeGreaterThan(0)
    expect(box!.height).toBeLessThan(page_!.height / 8)
  })

  test('given a box, when drawn, then it tints the paper without lifting the ink',
       async ({ app }) => {
    // Given a marked passage
    await citation(app)
    await rendered(app)
    const box = app.locator('.pdf-boxes span').first()

    // When the fill is read
    // Then it multiplies rather than veiling, and is confined to the page
    await expect(box).toHaveCSS('mix-blend-mode', 'multiply')
    await expect(app.locator('.pdf-stack').first())
      .toHaveCSS('isolation', 'isolate')
  })

  test('given the text layer, when it renders, then the page is selectable',
       async ({ app }) => {
    // Given a rendered page
    await citation(app)
    await rendered(app)

    // When the text layer is measured
    const size = await app.locator('.textLayer span').first().evaluate(
      (element) => parseFloat(getComputedStyle(element).fontSize))

    // Then its glyphs have a size, so a reader can select them
    expect(size).toBeGreaterThan(1)
  })

  test('given a parent section, when followed, then the panel moves to it',
       async ({ app }) => {
    // Given a cited passage printed inside another section
    await citation(app)
    const parent = panel(app).locator('.meta button.link')
    const heading = await parent.innerText()

    // When the parent is followed
    await parent.click()

    // Then the panel is showing that section instead
    await expect(panel(app).locator('h2')).toHaveText(heading)
  })

  test('given nothing cited, when the panel is opened, then the book is browsable',
       async ({ app }) => {
    // Given a panel opened from the toolbar with nothing cited
    await app.getByRole('button', { name: 'Book page' }).click()

    // When it draws
    // Then it is the SRD from page one, with a way to type a page number
    await expect(panel(app).getByLabel('Page')).toBeVisible()
    await expect(app.locator('.pdf-page').first()).toHaveAttribute('data-page', '1')
  })

  test('given a page number, when submitted, then the book scrolls to it',
       async ({ app }) => {
    // Given the book, open at the front
    await app.getByRole('button', { name: 'Book page' }).click()
    await expect(app.locator('.pdf-page').first()).toBeVisible()

    // When a page is asked for
    await panel(app).getByLabel('Page').fill('186')
    await panel(app).getByRole('button', { name: 'Go' }).click()

    // Then that page is what is in view
    await expect(app.locator('[data-page="186"]')).toBeInViewport({ ratio: 0.1 })
  })

  test('given the panel, when it is closed, then the conversation is undisturbed',
       async ({ app }) => {
    // Given an answered question with the panel open on a citation
    await citation(app)

    // When the panel is closed
    await panel(app).getByRole('button', { name: 'Close panel' }).click()

    // Then it is gone and the answer is still there
    await expect(panel(app)).toBeHidden()
    await expect(app.locator('.citations .chip').first()).toBeVisible()
  })

  test('given a remembered width, when the page reloads, then it is kept',
       async ({ app }) => {
    // Given the panel open and dragged narrower
    await app.getByRole('button', { name: 'Book page' }).click()
    const handle = app.getByRole('separator', { name: 'Resize the page panel' })
    await handle.click()
    await handle.press('ArrowRight')
    await handle.press('ArrowRight')
    const width = (await panel(app).boundingBox())!.width

    // When the page is reloaded
    await app.reload()
    await app.getByRole('button', { name: 'Book page' }).click()

    // Then the panel comes back the width it was left
    await expect(panel(app)).toBeVisible()
    expect((await panel(app).boundingBox())!.width).toBeCloseTo(width, 0)
  })
})
