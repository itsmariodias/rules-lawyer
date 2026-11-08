/** `useChat` and `SidePanel` are mocked; each has its own tests. */

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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

vi.mock('./useChat', () => ({ useChat: () => chat }))
// Has its own tests; the shell's tests assume a connected graph.
vi.mock('./useGraphStatus', () => ({ useGraphStatus: () => 'connected' }))
vi.mock('./components/SidePanel', () => ({
  SidePanel: ({ sectionId, tab }: { sectionId: string | null; tab: string }) =>
    <div data-testid="panel">{`${tab}:${sectionId ?? 'none'}`}</div>,
}))
vi.mock('./logo.svg?raw', () => ({ default: '<svg></svg>' }))

const thread = (overrides: Partial<Thread> = {}): Thread => ({
  thread_id: 't1', title: 'Prone condition', updated_at: '2026-01-01',
  messages: 2, pinned: false, ...overrides,
})

beforeEach(() => {
  Object.assign(chat, { messages: [], threads: [], threadId: null,
                        streaming: false })
  chat.forget.mockResolvedValue(undefined)
  // jsdom lacks showModal/close; without `open`, dialog contents are not
  // in the accessibility tree.
  HTMLDialogElement.prototype.showModal = vi.fn(function (
      this: HTMLDialogElement) { this.open = true })
  HTMLDialogElement.prototype.close = vi.fn(function (
      this: HTMLDialogElement) { this.open = false })
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
  it('given a failed turn, when rendered, then the error is the answer', () => {
    // Given a turn the model could not answer
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: '', error: 'The Gemini quota is spent' },
    ]

    // When it is rendered
    render(<App />)

    // Then the reader is told what went wrong, and offered nothing instead
    expect(screen.getByText('The Gemini quota is spent')).toBeInTheDocument()
    expect(screen.queryByRole('button',
                              { name: /SRD search instead/ })).toBeNull()
  })

  it('given a failed turn, when retried, then the question is asked again', async () => {
    // Given a turn the model could not answer, in a stored conversation
    chat.threadId = 't1'
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: '', error: 'The Gemini quota is spent' },
    ]
    render(<App />)

    // When the reader asks for it again, from the failure itself
    const failed = document.querySelector('.failed') as HTMLElement
    await userEvent.click(
      within(failed).getByRole('button', { name: 'Ask this question again' }))

    // Then the turn is re-run rather than retyped
    expect(chat.retry).toHaveBeenCalled()
  })

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

  it('given an answer, when copied, then the markdown goes to the clipboard', () => {
    // Given an answered turn and a clipboard to write to
    const writeText = vi.fn(() => Promise.resolve())
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'A Prone creature has Disadvantage [11.2.114].' },
    ]
    render(<App />)

    // When the answer is copied
    fireEvent.click(screen.getByRole('button', { name: 'Copy this answer' }))

    // Then the ids went with it
    expect(writeText).toHaveBeenCalledWith(
      'A Prone creature has Disadvantage [11.2.114].')
  })

  it('given a copy, when it lands, then the button says so', async () => {
    // Given an answered turn
    vi.stubGlobal('navigator',
                  { ...navigator, clipboard: { writeText: () => Promise.resolve() } })
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'A Prone creature.' },
    ]
    render(<App />)

    // When it is copied
    fireEvent.click(screen.getByRole('button', { name: 'Copy this answer' }))

    // Then the same button is the confirmation
    expect(await screen.findByRole('button', { name: 'Copied' }))
      .toBeInTheDocument()
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

  it('given an answer with no content yet, when rendered, then it says it is thinking', () => {
    // Given a turn that has started but said nothing
    chat.messages = [{ role: 'user', content: 'Prone?' },
                     { role: 'assistant', content: '' }]

    // When it is rendered
    const { container } = render(<App />)

    // Then the reader can see the thing is alive, with an ellipsis that
    // moves: an agentic turn is quiet for a whole round trip before it says
    // anything, and a static one reads as a hang.
    expect(screen.getByText(/Thinking/)).toBeInTheDocument()
    expect(container.querySelectorAll('.thinking .dots i')).toHaveLength(3)
  })

  it('given a turn in flight, when rendered, then the wait is counted up', () => {
    // Given a turn that has been running for a few seconds
    chat.streaming = true
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: '',
        at: new Date(Date.now() - 4200).toISOString() },
    ]

    // When it is rendered
    const { container } = render(<App />)

    // Then the wait so far is on screen
    expect(container.querySelector('.elapsed')?.textContent)
      .toMatch(/^4\.\ds$/)
  })

  it('given a finished turn, when rendered, then it is dated and timed', () => {
    // Given an answered turn that took a while
    chat.messages = [
      { role: 'user', content: 'Prone?', at: '2026-09-14T08:57:45.000Z' },
      { role: 'assistant', content: 'It does.', at: '2026-09-14T08:57:58.000Z',
        ms: 13_500 },
    ]

    // When it is rendered
    const { container } = render(<App />)

    // Then both turns carry the time they happened, and the answer what it
    // cost, with no counter still running under a finished answer
    expect(container.querySelectorAll('time.stamp')).toHaveLength(2)
    expect(container.querySelector('.took')).toHaveTextContent('14s')
    expect(container.querySelector('.elapsed')).toBeNull()
  })

  it('given what an answer cost, when rendered, then it is in the stamp\'s row', () => {
    // Given an answer with its tokens counted, and an older one without
    chat.messages = [
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'It does.', usage: null },
      { role: 'user', content: 'Grappled?' },
      { role: 'assistant', content: 'It is.',
        usage: { input: 17_790, output: 450, total: 18_240, calls: 5 } },
    ]

    // When they are rendered
    const { container } = render(<App />)

    // Then only the counted one says what it cost, on the same line as its time
    const counts = container.querySelectorAll('.usage')
    expect(counts).toHaveLength(1)
    expect(counts[0]).toHaveTextContent('18,240 tokens')
    expect(counts[0].parentElement).toHaveClass('timing')
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

describe('the thread list', () => {
  it('given conversations, when listed, then each is a row that opens it', async () => {
    // Given one stored conversation
    chat.threads = [thread()]
    render(<App />)

    // When its row is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Prone condition' }))

    // Then it is opened
    expect(chat.open).toHaveBeenCalledWith('t1')
  })

  it('given a pinned conversation, when listed, then it has a section of its own', () => {
    // Given one pinned conversation and one not
    chat.threads = [thread({ thread_id: 'p', title: 'Kept', pinned: true }),
                    thread()]

    // When the list is rendered
    render(<App />)

    // Then both groups are named
    expect(screen.getByRole('heading', { name: 'Pinned' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Conversations' }))
      .toBeInTheDocument()
  })

  it('given nothing pinned, when listed, then there is no empty Pinned section', () => {
    // Given only unpinned conversations
    chat.threads = [thread()]

    // When the list is rendered
    render(<App />)

    // Then the section appears only when something is in it
    expect(screen.queryByRole('heading', { name: 'Pinned' })).toBeNull()
  })

  it('given a row, when its menu is opened, then pin and delete are offered', async () => {
    // Given a conversation
    chat.threads = [thread()]
    render(<App />)

    // When its menu is opened
    await userEvent.click(screen.getByRole(
      'button', { name: 'Options for conversation: Prone condition' }))

    // Then the two things you can do to it are there
    const menu = screen.getByRole('menu')
    expect(within(menu).getByRole('menuitem', { name: /Pin/ }))
      .toBeInTheDocument()
    expect(within(menu).getByRole('menuitem', { name: /Delete/ }))
      .toBeInTheDocument()
  })

  it('given the menu, when pin is chosen, then the conversation is pinned', async () => {
    // Given an unpinned conversation's menu
    chat.threads = [thread()]
    render(<App />)
    await userEvent.click(screen.getByRole(
      'button', { name: 'Options for conversation: Prone condition' }))

    // When pin is chosen
    await userEvent.click(screen.getByRole('menuitem', { name: /Pin/ }))

    // Then the server is told, and the menu closes
    expect(chat.pin).toHaveBeenCalledWith('t1', true)
    expect(screen.queryByRole('menu')).toBeNull()
  })

  it('given a pinned conversation, when its menu is opened, then it offers to unpin', async () => {
    // Given a pinned conversation
    chat.threads = [thread({ pinned: true })]
    render(<App />)

    // When its menu is opened
    await userEvent.click(screen.getByRole(
      'button', { name: 'Options for conversation: Prone condition' }))

    // Then the action offered is the one that changes something
    expect(screen.getByRole('menuitem', { name: /Unpin/ })).toBeInTheDocument()
  })

  it('given an open menu, when Escape is pressed, then it closes', async () => {
    // Given an open menu
    chat.threads = [thread()]
    render(<App />)
    await userEvent.click(screen.getByRole(
      'button', { name: 'Options for conversation: Prone condition' }))

    // When Escape is pressed
    await userEvent.keyboard('{Escape}')

    // Then it is dismissed
    expect(screen.queryByRole('menu')).toBeNull()
  })
})

describe('deleting a conversation', () => {
  async function armDelete() {
    chat.threads = [thread()]
    render(<App />)
    await userEvent.click(screen.getByRole(
      'button', { name: 'Options for conversation: Prone condition' }))
    await userEvent.click(screen.getByRole('menuitem', { name: /Delete/ }))
  }

  it('given delete is chosen, when the dialog opens, then it asks first', async () => {
    // Given a conversation
    // When delete is chosen
    await armDelete()

    // Then nothing is deleted yet, and the conversation is named
    expect(chat.forget).not.toHaveBeenCalled()
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByRole(
      'heading', { name: 'Delete this conversation?' })).toBeInTheDocument()
    expect(within(dialog).getByText('Prone condition')).toBeInTheDocument()
  })

  it('given the dialog, when it opens, then Cancel has the focus', async () => {
    // Given the dialog
    await armDelete()

    // When the focus is read
    // Then it is on the button that does nothing
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('given the dialog, when Delete is pressed, then the conversation goes', async () => {
    // Given the dialog
    await armDelete()

    // When delete is confirmed
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    // Then it is deleted and the dialog closes
    expect(chat.forget).toHaveBeenCalledWith('t1')
    await waitFor(() => expect(screen.queryByRole('heading',
      { name: 'Delete this conversation?' })).toBeNull())
  })

  it('given the dialog, when Cancel is pressed, then nothing is deleted', async () => {
    // Given the dialog
    await armDelete()

    // When it is cancelled
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    // Then the conversation is untouched and the dialog is gone
    expect(chat.forget).not.toHaveBeenCalled()
    expect(screen.queryByRole('heading',
                              { name: 'Delete this conversation?' })).toBeNull()
  })

  it('given a delete that fails, when confirmed, then the dialog stays open', async () => {
    // Given a server that refuses the delete
    chat.forget.mockImplementationOnce(async () => { throw new Error('503') })
    await armDelete()

    // When delete is confirmed
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }))

    // Then the failure is shown, in the dialog that is still up
    expect(await screen.findByText(/503/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Delete this conversation?' }))
      .toBeInTheDocument()
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
