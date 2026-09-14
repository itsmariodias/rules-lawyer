/**
 * Conversation state for one thread.
 *
 * The server owns the history; this owns only what is on screen.  The
 * streaming assistant message is always the last element of `messages`, and
 * every event folds into it, so that is what these tests drive: events in,
 * rendered conversation out.
 */

import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatEvent } from './api'
import { useChat } from './useChat'

vi.mock('./api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api')>()),
  listThreads: vi.fn(() => Promise.resolve([])),
  loadThread: vi.fn(() => Promise.resolve([])),
  pinThread: vi.fn(() => Promise.resolve()),
  deleteThread: vi.fn(() => Promise.resolve()),
  streamChat: vi.fn(() => Promise.resolve()),
}))

const api = await import('./api')

/** Make `streamChat` deliver these events, then finish. */
function replying(...events: ChatEvent[]) {
  vi.mocked(api.streamChat).mockImplementation(
    async (_message, _threadId, onEvent) => {
      for (const event of events) onEvent(event)
    })
}

beforeEach(() => {
  vi.mocked(api.listThreads).mockResolvedValue([])
  vi.mocked(api.streamChat).mockResolvedValue(undefined)
})

describe('send', () => {
  it('given a question, when sent, then both turns appear at once', async () => {
    // Given a fresh conversation
    replying({ type: 'token', text: 'A Prone creature…' })
    const { result } = renderHook(() => useChat())

    // When a question is sent
    await act(() => result.current.send('Prone?'))

    // Then the question and the answer it is streaming into are both there
    expect(result.current.messages.map((m) => m.role))
      .toEqual(['user', 'assistant'])
    expect(result.current.messages[0].content).toBe('Prone?')
  })

  it('given tokens, when they arrive, then they append to the last message', async () => {
    // Given an answer streaming in pieces
    replying({ type: 'token', text: 'A Prone ' },
             { type: 'token', text: 'creature.' })
    const { result } = renderHook(() => useChat())

    // When the turn runs
    await act(() => result.current.send('Prone?'))

    // Then the pieces are one answer
    expect(result.current.messages[1].content).toBe('A Prone creature.')
  })

  it('given an empty question, when sent, then nothing is asked', async () => {
    // Given a fresh conversation
    const { result } = renderHook(() => useChat())

    // When only whitespace is sent
    await act(() => result.current.send('   '))

    // Then no turn was started
    expect(result.current.messages).toEqual([])
    expect(api.streamChat).not.toHaveBeenCalled()
  })

  it('given a turn in flight, when another is sent, then it is ignored', async () => {
    // Given a turn that never finishes
    vi.mocked(api.streamChat).mockImplementation(() => new Promise(() => {}))
    const { result } = renderHook(() => useChat())
    act(() => void result.current.send('Prone?'))
    await waitFor(() => expect(result.current.streaming).toBe(true))

    // When a second question is sent
    await act(() => result.current.send('Restrained?'))

    // Then the conversation is not interleaved
    expect(result.current.messages).toHaveLength(2)
  })
})

describe('apply', () => {
  it('given a start event, when it arrives, then the thread is remembered', async () => {
    // Given a first turn
    replying({ type: 'start', thread_id: 'minted' })
    const { result } = renderHook(() => useChat())

    // When it runs
    await act(() => result.current.send('Prone?'))

    // Then the id the server minted is what later turns will carry
    expect(result.current.threadId).toBe('minted')
  })

  it('given a tool call, when it starts and ends, then it is shown then marked done', async () => {
    /** A graph RAG answer is only trustworthy if you can see the retrieval. */
    // Given a turn that searches
    replying(
      { type: 'tool_start', id: 't1', name: 'search_srd', args: { query: 'Prone' } },
      { type: 'tool_end', id: 't1', name: 'search_srd', result_chars: 900 })
    const { result } = renderHook(() => useChat())

    // When it runs
    await act(() => result.current.send('Prone?'))

    // Then the trace shows the lookup, finished
    const tools = result.current.messages[1].tools ?? []
    expect(tools).toHaveLength(1)
    expect(tools[0]).toMatchObject({ name: 'search_srd', done: true })
  })

  it('given citations, when they arrive, then they hang off the answer', async () => {
    // Given a turn that cites
    replying({ type: 'citations',
               citations: [{ section_id: '11.2.114', heading: 'Prone',
                             entity_type: 'glossary_term', page: 186,
                             labels: ['Condition'] }] })
    const { result } = renderHook(() => useChat())

    // When it runs
    await act(() => result.current.send('Prone?'))

    // Then the chips are on the message they belong to
    expect(result.current.messages[1].citations?.[0].section_id)
      .toBe('11.2.114')
  })

  it('given a failed turn, when the error arrives, then it is the answer', async () => {
    /**
     * The model is required, so nothing stands in for it: the failure is
     * what the reader is given, not a banner over a substitute answer.
     */
    // Given a turn the model could not answer
    replying({ type: 'error', message: 'The Gemini quota is spent' })
    const { result } = renderHook(() => useChat())

    // When it runs
    await act(() => result.current.send('Prone?'))

    // Then the error is on the message, with nothing beside it
    expect(result.current.messages[1].error).toContain('quota')
    expect(result.current.messages[1].content).toBe('')
  })
})

describe('open', () => {
  it('given a stored conversation, when opened, then it is fetched, not cached', async () => {
    /** The server owns the history, which is why switching is a fetch. */
    // Given a conversation on the server
    vi.mocked(api.loadThread).mockResolvedValue([
      { role: 'user', content: 'Prone?' },
      { role: 'assistant', content: 'A Prone creature…' },
    ])
    const { result } = renderHook(() => useChat())

    // When it is opened
    await act(() => result.current.open('stored'))

    // Then what is on screen came from the server
    expect(api.loadThread).toHaveBeenCalledWith('stored')
    expect(result.current.threadId).toBe('stored')
    expect(result.current.messages).toHaveLength(2)
  })
})

describe('reset', () => {
  it('given a conversation on screen, when reset, then a new one starts', async () => {
    // Given an open conversation
    replying({ type: 'start', thread_id: 'abc' })
    const { result } = renderHook(() => useChat())
    await act(() => result.current.send('Prone?'))

    // When it is reset
    act(() => result.current.reset())

    // Then the next turn will mint its own thread
    expect(result.current.threadId).toBeNull()
    expect(result.current.messages).toEqual([])
  })
})

describe('forget', () => {
  it('given the conversation being read, when deleted, then it leaves the screen too', async () => {
    /**
     * Leaving its turns up with nothing behind them would invite a reply
     * into a thread that no longer exists.
     */
    // Given the open conversation
    replying({ type: 'start', thread_id: 'abc' })
    const { result } = renderHook(() => useChat())
    await act(() => result.current.send('Prone?'))

    // When it is deleted
    await act(() => result.current.forget('abc'))

    // Then the screen is cleared with it
    expect(api.deleteThread).toHaveBeenCalledWith('abc')
    expect(result.current.messages).toEqual([])
    expect(result.current.threadId).toBeNull()
  })

  it('given another conversation, when deleted, then the one being read stays', async () => {
    // Given an open conversation
    replying({ type: 'start', thread_id: 'abc' })
    const { result } = renderHook(() => useChat())
    await act(() => result.current.send('Prone?'))

    // When a different one is deleted
    await act(() => result.current.forget('other'))

    // Then the reader keeps their place
    expect(result.current.threadId).toBe('abc')
    expect(result.current.messages).toHaveLength(2)
  })
})

describe('pin', () => {
  it('given a conversation, when pinned, then the list is refetched', async () => {
    /**
     * The order is the server's: there is one answer to where a thread sits
     * and it is not the browser's.
     */
    // Given the thread list has been loaded once
    const { result } = renderHook(() => useChat())
    await waitFor(() => expect(api.listThreads).toHaveBeenCalled())
    const before = vi.mocked(api.listThreads).mock.calls.length

    // When a conversation is pinned
    await act(() => result.current.pin('abc', true))

    // Then the order is asked for again rather than resorted here
    expect(api.pinThread).toHaveBeenCalledWith('abc', true)
    expect(vi.mocked(api.listThreads).mock.calls.length)
      .toBeGreaterThan(before)
  })
})

describe('threads', () => {
  it('given a listing that fails, when loaded, then the list is empty rather than broken', async () => {
    // Given a server that cannot list the threads
    vi.mocked(api.listThreads).mockRejectedValue(new Error('offline'))

    // When the hook is rendered
    const { result } = renderHook(() => useChat())

    // Then the conversation still works, with an empty sidebar
    await waitFor(() => expect(result.current.threads).toEqual([]))
  })
})
