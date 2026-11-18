import type { Page } from '@playwright/test'

import { ask, expect, openSection, panel, test, tree } from '../fixtures'

/** Open the first citation of an answered question. */
async function citation(page: Page) {
  await ask(page, 'What does the Prone condition do?')
  await page.locator('.citations .chip').first().click()
  await expect(panel(page)).toBeVisible()
}

/** The page holding the cited passage's first box, among the whole book. */
const cited = (page: Page) => page.locator('.pdf-page:has(.pdf-boxes span)').first()

/**
 * Wait for the cited page to finish rendering.  The canvas exists at
 * placeholder size from the start; the text layer's first span appears only
 * after the scale is final.
 */
async function rendered(page: Page) {
  await expect(cited(page).locator('canvas'))
    .toBeVisible({ timeout: 30_000 })
  await expect(cited(page).locator('.textLayer span').first())
    .toBeAttached({ timeout: 30_000 })
}

test.describe('the page panel', () => {
  test('given a citation, when opened, then the book itself is rendered',
       async ({ app }) => {
    // Given a cited passage
    await citation(app)

    // When the panel draws it
    await rendered(app)

    // Then it is a rendered page of the PDF, captioned with its number,
    // scrolled into view with the rest of the book around it
    await expect(cited(app).locator('figcaption')).toHaveText(/^p\. \d+$/)
    await expect(cited(app)).toBeInViewport({ ratio: 0.1 })
    await expect(app.locator('.pdf-page').first()).toHaveAttribute('data-page', '1')
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
    const page_ = await cited(app).locator('canvas').boundingBox()
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
    const size = await cited(app).locator('.textLayer span').first().evaluate(
      (element) => parseFloat(getComputedStyle(element).fontSize))

    // Then its glyphs have a size, so a reader can select them
    expect(size).toBeGreaterThan(1)
  })

  test('given a nested citation, when its top-level ancestor is followed, then the panel moves to it',
       async ({ app }) => {
    // Given a cited passage, with its path through the book above the page
    await citation(app)
    await expect(openSection(app)).toBeVisible()
    // (the first crumb is SRD; the second is the top-level section)
    const top = tree(app).getByRole('listitem').nth(1).getByRole('button')
    const heading = await top.innerText()

    // When the top of that path is followed
    await top.click()

    // Then that section is the open one, right after SRD, and boxed
    await expect(tree(app).getByRole('listitem').nth(1)
      .locator('[aria-current="location"]')).toContainText(heading)
    await expect(app.locator('.pdf-boxes span').first()).toBeAttached()
  })

  test('given a citation, when the book is chosen in the path, then the boxes go and it returns to page 1',
       async ({ app }) => {
    // Given a cited passage, boxed
    await citation(app)
    await expect(app.locator('.pdf-boxes span').first()).toBeAttached()

    // When SRD, the first crumb of the path, is chosen
    await tree(app).getByRole('button', { name: 'SRD' }).click()

    // Then nothing is boxed, the book is back at page 1, and the top-level
    // sections are a dropdown away
    await expect(app.locator('.pdf-boxes span')).toHaveCount(0)
    await expect(app.locator('[data-page="1"]')).toBeInViewport({ ratio: 0.1 })
    await tree(app).getByRole('button', { name: 'Sections (16)' }).click()
    await expect(tree(app).getByRole('menuitem')).toHaveCount(16)
  })

  test('given a citation, when the panel is closed and reopened, then it is the whole book',
       async ({ app }) => {
    // Given a cited passage open in the panel
    await citation(app)

    // When the panel is closed and opened again from the toolbar
    await panel(app).getByRole('button', { name: 'Close panel' }).click()
    await app.getByRole('button', { name: 'Book page' }).click()

    // Then it is the whole book, with the page-jump to move through it
    await expect(panel(app).getByLabel('Page')).toBeVisible()
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
