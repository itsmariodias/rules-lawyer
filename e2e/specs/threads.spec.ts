import type { Page } from '@playwright/test'

import { ask, expect, test } from '../fixtures'

/** A question no other spec asks, so its row is unique. */
const unique = () => `What does the Prone condition do? (${Date.now()})`

const rowFor = (page: Page, title: string) =>
  page.locator('.thread').filter({ hasText: title })

/**
 * The row's title button.  The ⋯ button's accessible name also contains the
 * title, so match the role and class.
 */
const openerFor = (page: Page, title: string) =>
  rowFor(page, title).locator('.thread-open')

const pinOn = (page: Page, title: string) =>
  rowFor(page, title).locator('svg.pin')

/** Open the ⋯ menu on one conversation's row. */
async function menuFor(page: Page, title: string) {
  await rowFor(page, title).hover()
  await rowFor(page, title).getByRole('button', { name: /^Options for/ }).click()
  return page.getByRole('menu')
}

test.describe('the thread list', () => {
  test('given an answered question, when the turn ends, then it is listed',
       async ({ app }) => {
    // Given a question nobody else asked
    const question = unique()

    // When it is answered
    await ask(app, question)

    // Then the conversation is in the list, titled by the question
    await expect(rowFor(app, question)).toBeVisible({ timeout: 15_000 })
  })

  test('given a stored conversation, when the page reloads, then it can be reopened',
       async ({ app }) => {
    // Given an answered conversation
    const question = unique()
    await ask(app, question)
    await expect(rowFor(app, question)).toBeVisible({ timeout: 15_000 })

    // When the page is reloaded and the conversation reopened
    await app.reload()
    await openerFor(app, question).click()

    // Then both turns come back, with the citations resolved again
    await expect(app.locator('.message.user p')).toHaveText([question])
    await expect(app.locator('.citations .chip').first()).toBeVisible()

    await expect(app.locator('.trace-toggle')).toContainText('1 lookup')

    await expect(app.locator('.trace li')).toHaveCount(0)
    await app.locator('.trace-toggle').click()
    await expect(app.locator('.trace li')).toHaveClass(/done/)
    await expect(app.locator('.trace .outcome')).toContainText('passages')
  })

  test('given an answered conversation, when its path is reloaded, then it is still open',
       async ({ app }) => {
    // Given an answered conversation, now at its own path
    const question = unique()
    await ask(app, question)
    await expect(app).toHaveURL(/\/chat\/[0-9a-f]+$/)

    // When that path is reloaded
    await app.reload()

    // Then the conversation is on screen without opening it from the list
    await expect(app.locator('.message.user p')).toHaveText([question])
  })

  test('given two conversations, when Back is pressed, then the first returns',
       async ({ app }) => {
    // Given one conversation, then a new one
    const first = unique()
    await ask(app, first)
    await app.getByRole('button', { name: 'New conversation' }).click()
    await expect(app).toHaveURL(/\/$/)
    const second = unique()
    await ask(app, second)

    // When the browser goes back past the new chat
    await app.goBack()

    // Then the first conversation is on screen at its path
    await expect(app).toHaveURL(/\/chat\/[0-9a-f]+$/)
    await expect(app.locator('.message.user p')).toHaveText([first])
  })

  test('given a conversation, when pinned, then it moves to its own section',
       async ({ app }) => {
    // Given an answered conversation, with no Pinned section yet
    const question = unique()
    await ask(app, question)
    await expect(rowFor(app, question)).toBeVisible({ timeout: 15_000 })

    // When it is pinned
    await (await menuFor(app, question)).getByRole('menuitem', { name: 'Pin' })
      .click()

    // Then the section appears, and the conversation is in it, wearing a pin
    await expect(app.locator('.thread-group', { hasText: 'Pinned' }))
      .toBeVisible()
    await expect(pinOn(app, question)).toBeVisible()
    await expect(app.locator('.threads .thread').first())
      .toContainText(question)
  })

  test('given a pinned conversation, when unpinned, then it loses its pin',
       async ({ app }) => {
    // Given a pinned conversation
    const question = unique()
    await ask(app, question)
    await expect(rowFor(app, question)).toBeVisible({ timeout: 15_000 })
    await (await menuFor(app, question)).getByRole('menuitem', { name: 'Pin' })
      .click()
    await expect(app.locator('.thread-group', { hasText: 'Pinned' }))
      .toBeVisible()

    // When it is unpinned
    await (await menuFor(app, question)).getByRole('menuitem', { name: 'Unpin' })
      .click()

    // Then it is still listed, and no longer pinned
    // (the Pinned section itself may hold something an earlier test pinned)
    await expect(rowFor(app, question)).toBeVisible()
    await expect(pinOn(app, question)).toBeHidden()
  })

  test('given a delete, when it is confirmed, then the conversation is gone for good',
       async ({ app }) => {
    // Given an answered conversation
    const question = unique()
    await ask(app, question)
    await expect(rowFor(app, question)).toBeVisible({ timeout: 15_000 })

    // When delete is chosen and confirmed
    await (await menuFor(app, question)).getByRole('menuitem', { name: 'Delete' })
      .click()
    const dialog = app.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Delete' }).click()

    // Then it leaves the list and does not come back with the page
    await expect(rowFor(app, question)).toBeHidden()
    await app.reload()
    await expect(rowFor(app, question)).toBeHidden()
  })

  test('given the delete dialog, when it opens, then cancel is what has the focus',
       async ({ app }) => {
    // Given an answered conversation and the dialog open on it
    const question = unique()
    await ask(app, question)
    await expect(rowFor(app, question)).toBeVisible({ timeout: 15_000 })
    await (await menuFor(app, question)).getByRole('menuitem', { name: 'Delete' })
      .click()

    // When the focus is read, and Escape pressed
    await expect(app.getByRole('button', { name: 'Cancel' })).toBeFocused()
    await app.keyboard.press('Escape')

    // Then nothing was deleted
    await expect(app.getByRole('dialog')).toBeHidden()
    await expect(rowFor(app, question)).toBeVisible()
  })

  test('given a conversation, when a new one is started, then the thread is left behind',
       async ({ app }) => {
    // Given an answered conversation
    const question = unique()
    await ask(app, question)

    // When a new conversation is started
    await app.getByRole('button', { name: 'New conversation' }).click()

    // Then the screen is empty and the old one is still in the list
    await expect(app.locator('.message')).toHaveCount(0)
    await expect(app.getByRole('heading', { name: 'Rules Lawyer' })).toBeVisible()
    await expect(rowFor(app, question)).toBeVisible()
  })

  test('given the thread list, when it is hidden, then the rail keeps its controls',
       async ({ app }) => {
    // Given the open pane
    await app.getByRole('button', { name: 'Hide the thread list' }).click()

    // When the page is reloaded
    await app.reload()

    // Then it is still hidden, and both controls are still reachable
    await expect(app.getByRole('button', { name: 'Show the thread list' }))
      .toBeVisible()
    await expect(app.getByRole('button', { name: 'New conversation' }))
      .toBeVisible()
  })
})
