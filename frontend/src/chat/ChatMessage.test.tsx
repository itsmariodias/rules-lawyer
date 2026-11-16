import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Message } from '../api'
import { ChatMessage } from './ChatMessage'
import { Markdown } from './Markdown'

// The real component, counted.
vi.mock('./Markdown', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./Markdown')>()
  return { ...actual, Markdown: vi.fn(actual.Markdown) }
})

function message(props: Partial<Parameters<typeof ChatMessage>[0]> & { message: Message }) {
  const merged = { running: false, threadId: 't1', onCite: vi.fn(), ...props }
  return { ...render(<ChatMessage {...merged} />), props: merged }
}

describe('ChatMessage', () => {
  it('given a failed turn, when rendered, then the error is the answer', () => {
    // Given an answer the model could not give
    // When it is rendered
    message({ message: { role: 'assistant', content: '',
                         error: 'The Gemini quota is spent' } })

    // Then the reader is told what went wrong, and offered nothing instead
    expect(screen.getByText('The Gemini quota is spent')).toBeInTheDocument()
    expect(screen.queryByRole('button',
                              { name: /SRD search instead/ })).toBeNull()
  })

  it('given a failed turn, when retried, then the question is asked again', async () => {
    // Given a failed answer that may be retried
    const onRetry = vi.fn()
    message({ message: { role: 'assistant', content: '',
                         error: 'The Gemini quota is spent' },
              onRetry })

    // When the reader asks for it again, from the failure itself
    const failed = document.querySelector('.failed') as HTMLElement
    await userEvent.click(
      within(failed).getByRole('button', { name: 'Ask this question again' }))

    // Then the turn is re-run rather than retyped
    expect(onRetry).toHaveBeenCalled()
  })

  it('given no retry on offer, when rendered, then none is shown', () => {
    // Given a question and an answer with no retry handed to them
    message({ message: { role: 'user', content: 'Prone?' } })
    message({ message: { role: 'assistant', content: 'A Prone creature' } })

    // When they are read
    // Then neither offers one
    expect(screen.queryByRole('button',
                              { name: 'Ask this question again' })).toBeNull()
  })

  it('given an answer, when copied, then the markdown goes to the clipboard', () => {
    // Given an answer and a clipboard to write to
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    message({ message: { role: 'assistant',
                         content: 'A Prone creature has Disadvantage [11.2.114].' } })

    // When the answer is copied
    fireEvent.click(screen.getByRole('button', { name: 'Copy this answer' }))

    // Then the ids went with it
    expect(writeText).toHaveBeenCalledWith(
      'A Prone creature has Disadvantage [11.2.114].')
  })

  it('given a copy, when it lands, then the button says so', async () => {
    // Given an answer
    vi.stubGlobal('navigator',
                  { ...navigator, clipboard: { writeText: () => Promise.resolve() } })
    message({ message: { role: 'assistant', content: 'A Prone creature.' } })

    // When it is copied
    fireEvent.click(screen.getByRole('button', { name: 'Copy this answer' }))

    // Then the same button is the confirmation
    expect(await screen.findByRole('button', { name: 'Copied' }))
      .toBeInTheDocument()
  })

  it('given a copy, when a moment has passed, then the button offers to copy again', async () => {
    // Given an answer just copied
    vi.useFakeTimers()
    try {
      vi.stubGlobal('navigator',
                    { ...navigator, clipboard: { writeText: () => Promise.resolve() } })
      message({ message: { role: 'assistant', content: 'A Prone creature.' } })
      fireEvent.click(screen.getByRole('button', { name: 'Copy this answer' }))
      await act(() => vi.advanceTimersByTimeAsync(0))
      expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument()

      // When the confirmation has been shown for its 1.6 seconds
      await act(() => vi.advanceTimersByTimeAsync(1600))

      // Then the button is back to what it does
      expect(screen.getByRole('button', { name: 'Copy this answer' })).toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('given a clipboard that refuses, when copied, then no success is claimed', async () => {
    // Given a browser that denies the clipboard write
    vi.stubGlobal('navigator', { ...navigator, clipboard: {
      writeText: () => Promise.reject(new Error('NotAllowedError')) } })
    message({ message: { role: 'assistant', content: 'A Prone creature.' } })

    // When the answer is copied
    fireEvent.click(screen.getByRole('button', { name: 'Copy this answer' }))
    await new Promise((resolve) => setTimeout(resolve, 0))

    // Then the button still offers to copy rather than saying it did
    expect(screen.getByRole('button', { name: 'Copy this answer' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Copied' })).toBeNull()
  })

  it('given an answer with no content yet, when rendered, then it says it is thinking', () => {
    // Given a turn that has started but said nothing
    // When it is rendered
    const { container } = message({ message: { role: 'assistant', content: '' } })

    // Then the reader can see the thing is alive, with an ellipsis that
    // moves: an agentic turn is quiet for a whole round trip before it says
    // anything, and a static one reads as a hang.
    expect(screen.getByText(/Thinking/)).toBeInTheDocument()
    expect(container.querySelectorAll('.thinking .dots i')).toHaveLength(3)
  })

  it('given a turn in flight, when rendered, then the wait is counted up', () => {
    // Given an answer that has been streaming for a few seconds
    // When it is rendered
    const { container } = message({
      running: true,
      message: { role: 'assistant', content: '',
                 at: new Date(Date.now() - 4200).toISOString() },
    })

    // Then the wait so far is on screen
    expect(container.querySelector('.elapsed')?.textContent)
      .toMatch(/^4\.\ds$/)
  })

  it('given an answer still streaming text, when rendered, then the wait is counted beside the stamp', () => {
    // Given an answer that has started writing and is not done
    // When it is rendered
    const { container } = message({
      running: true,
      message: { role: 'assistant', content: 'A Prone creature',
                 at: new Date(Date.now() - 2300).toISOString() },
    })

    // Then the counter has moved from "Thinking" to the timing row
    expect(container.querySelector('.timing .elapsed')?.textContent)
      .toMatch(/^2\.\ds$/)
    expect(screen.queryByText(/Thinking/)).toBeNull()
  })

  it('given a finished turn, when rendered, then it is dated and timed', () => {
    // Given an answered turn that took a while
    // When both of its messages are rendered
    message({ message: { role: 'user', content: 'Prone?',
                         at: '2026-09-14T08:57:45.000Z' } })
    message({ message: { role: 'assistant', content: 'It does.',
                         at: '2026-09-14T08:57:58.000Z', ms: 13_500 } })

    // Then both carry the time they happened, and the answer what it took,
    // with no counter still running under a finished answer
    expect(document.querySelectorAll('time.stamp')).toHaveLength(2)
    expect(document.querySelector('.took')).toHaveTextContent('14s')
    expect(document.querySelector('.elapsed')).toBeNull()
  })

  it('given what an answer cost, when rendered, then it is in the stamp\'s row', () => {
    // Given an answer with its tokens counted, and an older one without
    // When they are rendered
    message({ message: { role: 'assistant', content: 'It does.', usage: null } })
    message({ message: { role: 'assistant', content: 'It is.',
                         usage: { input: 17_790, output: 450, total: 18_240,
                                  calls: 5 } } })

    // Then only the counted one says what it cost, on the same line as its time
    const counts = document.querySelectorAll('.usage')
    expect(counts).toHaveLength(1)
    expect(counts[0]).toHaveTextContent('18,240 tokens')
    expect(counts[0].parentElement).toHaveClass('timing')
  })

  it('given citations, when a chip is pressed, then the section is cited', async () => {
    // Given an answer with a citation chip
    const { props } = message({ message: {
      role: 'assistant', content: 'A Prone creature…',
      citations: [{ section_id: '11.2.114', heading: 'Prone [Condition]',
                    entity_type: 'glossary_term', page: 186,
                    labels: ['Condition'] }],
    } })

    // When the chip is pressed
    await userEvent.click(screen.getByRole('button', { name: /Prone \[Condition\]/ }))

    // Then the section it names is what is opened
    expect(props.onCite).toHaveBeenCalledWith('11.2.114')
  })

  it('given an earlier answer, when the conversation re-renders, then it is not redrawn', () => {
    // Given an answer on screen
    const props = { message: { role: 'assistant', content: 'It does.' } as Message,
                    running: false, threadId: 't1', onCite: vi.fn() }
    const { rerender } = render(<ChatMessage {...props} />)
    vi.mocked(Markdown).mockClear()

    // When its parent re-renders with the same props, as on every token
    rerender(<ChatMessage {...props} />)

    // Then its markdown is not parsed again
    expect(Markdown).not.toHaveBeenCalled()
  })
})
