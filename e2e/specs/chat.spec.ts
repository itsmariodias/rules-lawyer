/**
 * Asking a question, end to end.
 *
 * The whole contract in one flow: the question is sent, the retrieval is
 * shown as it happens, tokens stream in, and the finished answer resolves
 * into citations that open the passage they came from.
 *
 * The server runs with `CHAT_STUB=1`, so the sentences come from a scripted
 * model rather than from Gemini — which is what makes this deterministic.
 * Everything around them is real: the search, the citations, the passage
 * each one opens.
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
    /** A graph RAG answer is only trustworthy if you can see the retrieval. */
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
    /**
     * The counts say a search found three passages; this says which three.
     * Fetched on demand rather than sent with the turn, so the request is
     * part of what is being tested.
     */
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

    /**
     * Then each is a number and the heading it names. The list is the legend
     * for the numbers in the prose, and the section id is how the app finds
     * the passage rather than something a reader wants to read.
     */
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

    // The chip shows a number and the heading, so the id it opens comes off
    // the title rather than the label.
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
    /**
     * The rewrite into links is what makes a citation inside a table cell or
     * a list item behave like any other.
     */
    // Given an answer whose text carries an inline citation
    await ask(app, 'What does the Prone condition do?')
    const cite = app.locator('.prose button.cite').first()

    // It reads as a number: a dotted id means nothing to a reader, and one
    // section cited five times was five identical chips of it.
    await expect(cite).toHaveText(/^\d+$/)

    // The id it opens is still there, one hover away
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
    /** The thread is a conversation, not a series of one-shot answers. */
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
    /**
     * A retry rewinds the checkpoint rather than appending to it, which only
     * a round trip through the real server can show: on screen the two look
     * the same until the conversation is reopened.
     */
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
