/** `useChat` and `SidePanel` are mocked; each has its own tests. */

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import type { Message, Thread } from './api'

const chat = {
  messages: [] as Message[],
  threads: [] as Thread[],
  threadId: null as string | null,
  streaming: false,
  send: vi.fn(),
  retry: vi.fn(),
  stop: vi.fn(),
  open: vi.fn(),
  reset: vi.fn(),
  forget: vi.fn(() => Promise.resolve()),
  pin: vi.fn(() => Promise.resolve()),
}

vi.mock('./chat/useChat', () => ({ useChat: () => chat }))
// Has its own tests; the shell's tests assume a connected graph.
vi.mock('./sidebar/useGraphStatus', () => ({ useGraphStatus: () => 'connected' }))
vi.mock('./panel/SidePanel', () => ({
  SidePanel: ({ sectionId, tab, onClose }: {
    sectionId: string | null; tab: string; onClose: () => void
  }) => (
    <div data-testid="panel">
      {`${tab}:${sectionId ?? 'none'}`}
      <button onClick={onClose}>Close panel</button>
    </div>
  ),
}))
vi.mock('./logo.svg?raw', () => ({ default: '<svg></svg>' }))

beforeEach(() => {
  Object.assign(chat, { messages: [], threads: [], threadId: null,
                        streaming: false })
  Element.prototype.scrollIntoView = vi.fn()
})

describe('the welcome screen', () => {
  it('given no messages, when rendered, then the examples are offered', () => {
    // Given an empty conversation
    render(<App />)

    // When the screen is read
    // Then it says what this is and offers somewhere to start
    expect(screen.getByRole('heading', { name: /Rules Lawyer/ }))
      .toBeInTheDocument()
    expect(screen.getByRole('button',
                            { name: 'What exactly does the Prone condition do?' }))
      .toBeInTheDocument()
  })

  it('given an example, when pressed, then it is asked', async () => {
    // Given the welcome screen
    render(<App />)

    // When an example is pressed
    await userEvent.click(screen.getByRole(
      'button', { name: 'What exactly does the Prone condition do?' }))

    // Then it is sent as the question
    expect(chat.send)
      .toHaveBeenCalledWith('What exactly does the Prone condition do?')
  })
})

describe('the composer', () => {
  it('given an empty box, when read, then there is nothing to send', () => {
    // Given nothing typed
    render(<App />)

    // When the send button is read
    // Then it cannot be pressed
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()
  })

  it('given a question, when Enter is pressed, then it is sent', async () => {
    // Given a typed question
    render(<App />)
    const box = screen.getByPlaceholderText('Ask a rules question…')
    await userEvent.type(box, 'Prone?')

    // When Enter is pressed
    await userEvent.keyboard('{Enter}')

    // Then it is asked, and the box is emptied
    expect(chat.send).toHaveBeenCalledWith('Prone?')
    expect(box).toHaveValue('')
  })

  it('given a question, when Shift+Enter is pressed, then it is a newline', async () => {
    // Given a typed question
    render(<App />)
    await userEvent.type(screen.getByPlaceholderText('Ask a rules question…'),
                         'Prone?')

    // When Shift+Enter is pressed
    await userEvent.keyboard('{Shift>}{Enter}{/Shift}')

    // Then nothing was sent
    expect(chat.send).not.toHaveBeenCalled()
  })

  it('given a turn in flight, when rendered, then it can be stopped', async () => {
    // Given a streaming answer
    chat.streaming = true
    render(<App />)

    // When the composer is read
    await userEvent.click(screen.getByRole('button', { name: 'Stop' }))

    // Then the turn can be abandoned rather than only waited out
    expect(chat.stop).toHaveBeenCalled()
  })
})

describe('the conversation', () => {
  it('given a turn being written, when rendered, then it cannot be retried', () => {
    // Given an answer still streaming
    chat.threadId = 't1'
    chat.streaming = true
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'A Prone creature' },
    ]

    // When it is rendered
    render(<App />)

    // Then nothing offers to replace it yet
    expect(screen.queryByRole('button',
                              { name: 'Ask this question again' })).toBeNull()
  })

  it('given an answer, when rendered, then only the last turn offers a retry', () => {
    // Given a conversation of two answered turns
    chat.threadId = 't1'
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'A Prone creature' },
      { role: 'user', content: 'Restrained?' },
      { role: 'assistant', content: 'A Restrained creature' },
    ]

    // When it is rendered
    render(<App />)

    // Then the last turn offers it twice over, and the turn above not at all
    expect(screen.getAllByRole('button',
                               { name: 'Ask this question again' }))
      .toHaveLength(2)
    const turns = document.querySelectorAll('.message')
    expect(within(turns[0] as HTMLElement).queryByRole(
      'button', { name: 'Ask this question again' })).toBeNull()
    expect(within(turns[1] as HTMLElement).queryByRole(
      'button', { name: 'Ask this question again' })).toBeNull()
  })

  it('given a conversation, when rendered, then every answer can be copied', () => {
    // Given two answered turns
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'A Prone creature' },
      { role: 'user', content: 'Restrained?' },
      { role: 'assistant', content: 'A Restrained creature' },
    ]

    // When it is rendered
    render(<App />)

    // Then the offer is on both, unlike the retry
    expect(screen.getAllByRole('button', { name: 'Copy this answer' }))
      .toHaveLength(2)
  })

  it('given any screen, when rendered, then the SRD attribution is on it', () => {
    /**
     * CC BY 4.0 requires the attribution verbatim, with or without a
     * conversation.
     */
    // Given nothing asked yet
    chat.messages = []

    // When the app is rendered
    render(<App />)

    // Then the licence's own wording is present, and it is the whole of it
    expect(screen.getByText(/This work includes material from the System/))
      .toBeInTheDocument()
    expect(screen.getByRole('link',
                            { name: 'https://www.dndbeyond.com/srd' }))
      .toBeInTheDocument()
    expect(screen.getByRole(
      'link', { name: 'https://creativecommons.org/licenses/by/4.0/legalcode' },
    )).toBeInTheDocument()
  })

  it('given citations, when a chip is pressed, then the panel opens on the page', async () => {
    // Given an answer with a citation chip
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'A Prone creature…',
        citations: [{ section_id: '11.2.114', heading: 'Prone [Condition]',
                      entity_type: 'glossary_term', page: 186,
                      labels: ['Condition'] }] },
    ]
    render(<App />)

    // When the chip is pressed
    await userEvent.click(screen.getByRole('button', { name: /Prone \[Condition\]/ }))

    // Then the panel opens on that passage's page
    expect(screen.getByTestId('panel')).toHaveTextContent('page:11.2.114')
  })

  it('given an open citation, when the panel is closed and reopened, then it shows the whole book', async () => {
    // Given a citation open in the panel
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'Disadvantage [11.2.114].' },
    ]
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '1' }))

    // When the panel is closed and the book is opened from the toolbar
    await userEvent.click(screen.getByRole('button', { name: 'Close panel' }))
    await userEvent.click(screen.getByRole('button', { name: 'Book page' }))

    // Then it opens on the whole book, not the old citation
    expect(screen.getByTestId('panel')).toHaveTextContent('page:none')
  })

  it('given an open citation, when its toolbar tab closes the panel, then the citation is cleared', async () => {
    // Given a citation open on the Page tab
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'Disadvantage [11.2.114].' },
    ]
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '1' }))

    // When the Page tab is pressed twice: once to close, once to reopen
    await userEvent.click(screen.getByRole('button', { name: 'Book page' }))
    await userEvent.click(screen.getByRole('button', { name: 'Book page' }))

    // Then it reopens on the whole book
    expect(screen.getByTestId('panel')).toHaveTextContent('page:none')
  })

  it('given an inline citation, when pressed, then it opens the same passage', async () => {
    // Given an answer citing inline
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'Disadvantage [11.2.114].' },
    ]
    render(<App />)

    // When the citation in the prose is pressed, which reads as a number
    // even though the id is what it opens
    await userEvent.click(screen.getByRole('button', { name: '1' }))

    // Then the panel opens on it
    expect(screen.getByTestId('panel')).toHaveTextContent('page:11.2.114')
  })
})

describe('the toolbar', () => {
  it('given a closed panel, when a tab is pressed, then it opens on that tab', async () => {
    // Given the panel closed
    render(<App />)

    // When the graph tab is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))

    // Then it opens there, with nothing cited
    expect(screen.getByTestId('panel')).toHaveTextContent('graph:none')
  })

  it('given the tab already showing, when pressed again, then the panel closes', async () => {
    // Given the panel open on the book
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: 'Book page' }))

    // When the same tab is pressed again
    await userEvent.click(screen.getByRole('button', { name: 'Book page' }))

    // Then the panel is gone
    expect(screen.queryByTestId('panel')).toBeNull()
  })

  it('given the panel open, when the other tab is pressed, then it switches', async () => {
    // Given the panel open on the book
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: 'Book page' }))

    // When the graph tab is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))

    // Then the panel stays open, showing the other question about the same place
    expect(screen.getByTestId('panel')).toHaveTextContent('graph:')
  })

  it('given the graph tab is open, when a citation is made, then it stays on the graph', async () => {
    // Given the panel open on the graph
    chat.messages = [{ role: 'assistant', content: 'See [11.2.114].' }]
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))

    // When a citation is pressed
    await userEvent.click(screen.getByRole('button', { name: '1' }))

    // Then the reader keeps their tab, on the new passage
    expect(screen.getByTestId('panel')).toHaveTextContent('graph:11.2.114')
  })
})

describe('the sidebar', () => {
  it('given the thread list, when it is hidden, then a rail keeps its controls', async () => {
    // Given the open pane
    render(<App />)

    // When it is hidden
    await userEvent.click(screen.getByRole('button',
                                           { name: 'Hide the thread list' }))

    // Then it can be brought back, and a conversation can still be started
    expect(screen.getByRole('button', { name: 'Show the thread list' }))
      .toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'New conversation' }))
      .toBeInTheDocument()
  })

  it('given a hidden thread list, when the page reloads, then it stays hidden', async () => {
    // Given the pane hidden in an earlier session
    render(<App />)
    await userEvent.click(screen.getByRole('button',
                                           { name: 'Hide the thread list' }))

    // When the app is rendered again
    cleanupAndRender()

    // Then the preference survived
    expect(screen.getByRole('button', { name: 'Show the thread list' }))
      .toBeInTheDocument()
  })

  it('given the thread list, when the window is read, then it has no handle to drag', async () => {
    // Given the panel closed
    render(<App />)

    // When the separators are counted
    // Then there are none: the thread list is a fixed width
    expect(screen.queryAllByRole('separator')).toHaveLength(0)

    // And when the panel opens, only its own handle appears
    await userEvent.click(screen.getByRole('button', { name: 'Book page' }))
    expect(screen.getAllByRole('separator')).toHaveLength(1)
    expect(screen.getByRole('separator', { name: 'Resize the page panel' }))
      .toBeInTheDocument()
  })

  it('given a panel width stored on a wider screen, when the app loads, then the panel gives way', async () => {
    /**
     * Regression: a 1000px panel stored on a large display squeezed the
     * conversation on a laptop.
     */
    // Given a width stored on a large display, and a laptop-sized window
    const width = window.innerWidth
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1512 })
    localStorage.setItem('panel-width', '1000')
    try {
      render(<App />)

      // When the panel opens
      await userEvent.click(screen.getByRole('button', { name: 'Book page' }))

      // Then it takes what the thread list and the conversation leave
      expect(screen.getByRole('separator', { name: 'Resize the page panel' }))
        .toHaveAttribute('aria-valuenow', String(1512 - 260 - 420))
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
      localStorage.removeItem('panel-width')
    }
  })
})

/** Unmount and render again, as a reload would. */
function cleanupAndRender() {
  document.body.innerHTML = ''
  render(<App />)
}
