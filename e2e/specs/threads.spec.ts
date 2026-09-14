/**
 * Conversations: kept, reopened, pinned and deleted.
 *
 * This is the flow that outlives the page. The server owns the history —
 * there is no thread table, only checkpoints — so "the conversation is
 * still there after a reload" is a claim about SQLite, the checkpointer and
 * the thread id the browser held, and only a real stack can settle it.
 */

import type { Page } from '@playwright/test'

import { ask, expect, test } from '../fixtures'

/** A question nothing else in the run will ask, so its row is findable. */
const unique = () => `What does the Prone condition do? (${Date.now()})`

const rowFor = (page: Page, title: string) =>
  page.locator('.thread').filter({ hasText: title })

/** The row's own title button, not the `⋯` beside it — whose accessible
    name carries the title too, so a name alone matches both. */
const openerFor = (page: Page, title: string) =>
  rowFor(page, title).locator('.thread-open')

/** A pinned row wears a pin; which section it sits in is then a detail. */
const pinOn = (page: Page, title: string) =>
  rowFor(page, title).locator('svg.pin')

/** Open the menu on one conversation's row. */
async function menuFor(page: Page, title: string) {
  await rowFor(page, title).hover()
  await rowFor(page, title).getByRole('button', { name: /^Options for/ }).click()
  return page.getByRole('menu')
}

test.describe('the thread list', () => {
  test('given an answered question, when the turn ends, then it is listed',
       async ({ app }) => {
    /** The sidebar changes when a thread is created, so it is refreshed
        after a turn rather than during one. */
    // Given a question nobody else asked
    const question = unique()

    // When it is answered
    await ask(app, question)

    // Then the conversation is in the list, titled by the question
    await expect(rowFor(app, question)).toBeVisible({ timeout: 15_000 })
  })

  test('given a stored conversation, when the page reloads, then it can be reopened',
       async ({ app }) => {
    /**
     * The server owns the history, which is why reopening is a fetch and
     * not a cache lookup — and why this survives a reload at all.
     */
    // Given an answered conversation
    const question = unique()
    await ask(app, question)
    await expect(rowFor(app, question)).toBeVisible({ timeout: 15_000 })

    // When the page is reloaded and the conversation reopened
    await app.reload()
    await openerFor(app, question).click()

    // Then both turns come back, with the citations resolved again
    await expect(app.locator('.message.user')).toHaveText([question])
    await expect(app.locator('.citations .chip').first()).toBeVisible()
  })

  test('given a conversation, when pinned, then it moves to its own section',
       async ({ app }) => {
    /**
     * Ordering alone said which came first and nothing about why, so a pin
     * looked like luck; a heading says what the group *is*.
     */
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
    /** There is no undo — the checkpointer is the whole store. */
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
    /**
     * With no undo, the key someone presses without reading has to be the
     * one that changes nothing — and Escape agrees with it.
     */
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
    /** Collapsed, the pane keeps the width of its own controls. */
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
