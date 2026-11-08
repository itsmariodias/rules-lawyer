/**
 * Runs with `CHAT_STUB=1`: the model's wording is scripted, everything else is
 * live.
 */

import { ask, expect, test } from '../fixtures'

test.describe('asking a question', () => {
  test('given the welcome screen, when an example is pressed, then it is asked',
       async ({ app }) => {
    // Given the welcome screen, before anything has been asked
    await expect(app.getByRole('heading', { name: 'Rules Lawyer' }))
      .toBeVisible()

    // When one of the examples is pressed
    await app.getByRole('button',
                        { name: 'What exactly does the Prone condition do?' })
      .click()

    // Then it becomes the question, and an answer is on its way
    await expect(app.locator('.message.user p'))
      .toHaveText('What exactly does the Prone condition do?')
    await expect(app.locator('.message.assistant')).toBeVisible()
  })

  test('given a question, when it is answered, then the retrieval is on show',
       async ({ app }) => {
    // Given a question
    await ask(app, 'What does the Prone condition do?')

    // When the trace is read
    // Then it says what was searched for, that it finished, and what it found
    await expect(app.locator('.trace')).toContainText('Searched the SRD')
    await expect(app.locator('.trace li')).toHaveClass(/done/)
    await expect(app.locator('.trace .outcome')).toContainText('passages')
  })

  test('given an answered turn, when read, then it is dated and timed',
       async ({ app }) => {
    // Given an answered question
    await ask(app, 'What does the Prone condition do?')

    // When the turn is read
    // Then it says when it happened and what the wait cost
    await expect(app.locator('.message.user time.stamp')).toBeVisible()
    await expect(app.locator('.message.assistant .timing .took'))
      .toContainText(/\ds/)
  })

  test('given a lookup, when it is opened, then it shows what it returned',
       async ({ app }) => {
    // Given an answered question
    await ask(app, 'What does the Prone condition do?')
    await expect(app.locator('.trace li')).toHaveClass(/done/)

    // When its row is opened
    await app.locator('.trace .line').first().click()

    // Then the passages the model was given are under it
    await expect(app.locator('.trace .detail')).toBeVisible()
    await expect(app.locator('.trace .detail')).toContainText('Prone')
    await expect(app.locator('.trace .detail-label').last()).toHaveText('result')
  })

  test('given a finished answer, when it resolves, then it cites the book',
       async ({ app }) => {
    // Given an answered question about a condition
    await ask(app, 'What does the Prone condition do?')

    // When the citations are read
    const chips = app.locator('.citations .chip')

    await expect(chips.first()).toBeVisible()
    for (const [index, chip] of (await chips.all()).entries()) {
      await expect(chip.locator('.chip-id')).toHaveText(String(index + 1))
      await expect(chip).toHaveAttribute('title', /^SRD section \d+(\.\d+)+$/)
    }
  })

  test('given a citation chip, when pressed, then the panel opens on the passage',
       async ({ app }) => {
    // Given an answer carrying citations
    await ask(app, 'What does the Prone condition do?')
    const chip = app.locator('.citations .chip').first()

    // The chip label is a number and heading; the id is in its title.
    const id = (await chip.getAttribute('title'))
      ?.replace('SRD section ', '')
    expect(id).toBeTruthy()

    // When the chip is pressed
    await chip.click()

    // Then the panel opens on exactly that section
    await expect(app.locator('aside.panel')).toBeVisible()
    await expect(app.locator('aside.panel .meta code')).toHaveText(id!)
  })

  test('given a citation in the prose, when pressed, then it opens the same way',
       async ({ app }) => {
    // Given an answer whose text carries an inline citation
    await ask(app, 'What does the Prone condition do?')
    const cite = app.locator('.prose button.cite').first()

    // Rendered as a number, not the dotted id
    await expect(cite).toHaveText(/^\d+$/)

    // with the id in its title
    const title = await cite.getAttribute('title')
    const id = title?.match(/\(([\d.]+)\)$/)?.[1]
    expect(id).toBeTruthy()

    // When it is pressed
    await cite.click()

    // Then the panel opens on exactly that section
    await expect(app.locator('aside.panel .meta code')).toHaveText(id!)
  })

  test('given a first question, when a second is asked, then both turns remain',
       async ({ app }) => {
    // Given one answered question
    await ask(app, 'What does the Prone condition do?')

    // When a second is asked
    await ask(app, 'What does the Restrained condition do?')

    // Then the conversation holds both, in order
    await expect(app.locator('.message.user')).toHaveCount(2)
    await expect(app.locator('.message.assistant')).toHaveCount(2)
    await expect(app.locator('.message.user p').first())
      .toContainText('Prone')
  })

  test('given an answered turn, when retried, then it is replaced, not repeated',
       async ({ app }) => {
    // Given an answered question
    await ask(app, 'What does the Prone condition do?')

    // When it is asked again. Both halves of the turn offer it; this is the
    // one under the answer.
    await app.getByRole('button', { name: 'Ask this question again' })
      .last().click()
    await expect(app.locator('.citations .chip').first())
      .toBeVisible({ timeout: 30_000 })

    // Then the conversation still holds that one question, reload and all
    await expect(app.locator('.message.user')).toHaveCount(1)
    await app.reload()
    await app.locator('.thread .thread-open').first().click()
    await expect(app.locator('.message.user')).toHaveCount(1)
    await expect(app.locator('.message.assistant')).toHaveCount(1)
  })

  test('given an empty box, when read, then there is nothing to send',
       async ({ app }) => {
    // Given nothing typed
    // When the send button is read
    // Then it cannot be pressed
    await expect(app.getByRole('button', { name: 'Send' })).toBeDisabled()
  })
})
