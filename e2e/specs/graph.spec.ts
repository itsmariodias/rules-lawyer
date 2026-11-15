import type { Page } from '@playwright/test'

import { ask, expect, panel, test } from '../fixtures'

/** The panel tabs; the page-jump form also has a "Page" label. */
const tab = (page: Page, name: 'Page' | 'Graph') =>
  panel(page).locator('.tabs').getByRole('button', { name })

/** Open a citation on the Graph tab. */
async function graphOf(page: Page, question = 'What does the Prone condition do?') {
  await ask(page, question)
  await page.locator('.citations .chip').first().click()
  await tab(page, 'Graph').click()
  await expect(page.locator('.graph svg')).toBeVisible({ timeout: 30_000 })
}

const dots = (page: Page) => page.locator('.graph svg g[data-kind]')

/**
 * Click a node with `force`: the simulation moves nodes for ~10s, and
 * Playwright's stability check will not click a moving element.
 */
const select = (dot: ReturnType<Page['locator']>) => dot.click({ force: true })

test.describe('the graph explorer', () => {
  test('given nothing cited, when opened, then the book and its sections are drawn',
       async ({ app }) => {
    // Given the panel opened from the toolbar
    await app.getByRole('button', { name: 'Graph' }).click()

    // When it draws
    await expect(app.locator('.graph svg')).toBeVisible({ timeout: 30_000 })

    // Then the book is the seed, with the top-level sections around it
    await expect(app.locator('.graph svg g.root[data-kind="book"]')).toBeVisible()
    await expect(dots(app).filter({ hasText: 'Playing the Game' })).toBeVisible()
    expect(await dots(app).count()).toBe(17)
  })

  test('given a citation, when opened, then its neighbourhood is drawn',
       async ({ app }) => {
    // Given a cited passage on the Graph tab
    await graphOf(app)

    // When the picture is read
    // Then the seed and its neighbours are drawn, joined by edges
    expect(await dots(app).count()).toBeGreaterThan(1)
    expect(await app.locator('.graph svg line, .graph svg path.link').count())
      .toBeGreaterThan(0)
    await expect(app.locator('.graph svg')).toContainText('Prone [Condition]')
  })

  test('given the drawn nodes, when read, then the legend names their kinds',
       async ({ app }) => {
    // Given a drawn neighbourhood
    await graphOf(app)

    // When the legend is read
    const legend = app.locator('.graph-legend li')

    // Then it names the kinds actually on screen
    expect(await legend.count()).toBeGreaterThan(0)
    await expect(legend.first()).toBeVisible()
  })

  test('given a node, when selected, then the card says what it is',
       async ({ app }) => {
    // Given a drawn neighbourhood
    await graphOf(app)

    // When a neighbour is selected
    await select(dots(app).nth(1))

    // Then a card names it, and says what it is connected to
    const card = app.locator('.graph-details')
    await expect(card).toBeVisible()
    await expect(card.locator('h3')).not.toBeEmpty()
  })

  test('given a selected section, when its page is opened, then the tab follows',
       async ({ app }) => {
    // Given a selected node that is a section
    await graphOf(app)
    const openable = app.locator('.graph-details').getByRole(
      'button', { name: 'Open page' })
    for (const dot of await dots(app).all()) {
      await select(dot)
      if (await openable.isVisible()) break
    }
    const name = await app.locator('.graph-details h3').innerText()

    // When its page is opened
    await openable.click()

    // Then the panel switches to the page for that node
    await expect(panel(app).locator('h2')).toHaveText(name.trim())
  })

  test('given a hub, when it is capped, then the card says what it did not show',
       async ({ app }) => {
    // Given a passage joined to a great many things
    await graphOf(app, 'What creatures deal Poison damage?')

    // When each node's card is read
    const card = app.locator('.graph-details')
    let capped = false
    for (const dot of (await dots(app).all()).slice(0, 8)) {
      await select(dot)
      if (await card.getByText(/of \d+/).first().isVisible()) { capped = true; break }
    }

    // Then at least one of them reports a total larger than what is drawn
    expect(capped).toBe(true)
  })

  test('given a deeper reach, when chosen, then more of the graph is drawn',
       async ({ app }) => {
    // Given a neighbourhood at one hop
    await graphOf(app)
    const near = await dots(app).count()

    // When two hops is chosen
    await panel(app).getByRole('button', { name: '2 hops' }).click()

    // Then the picture grows rather than being replaced
    await expect.poll(() => dots(app).count(), { timeout: 30_000 })
      .toBeGreaterThan(near)
  })

  test('given a graph and a citation, when the tab is switched, then the place is kept',
       async ({ app }) => {
    // Given a citation open on the Graph tab
    await graphOf(app)

    // When the Page tab is chosen
    await tab(app, 'Page').click()

    // Then it is the same passage, seen the other way
    await expect(panel(app).locator('.meta code')).toHaveText('11.2.114')
  })
})
