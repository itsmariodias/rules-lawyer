import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ChatEvent } from '../api'
import { useChat } from './useChat'

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  listThreads: vi.fn(() => Promise.resolve([])),
  loadThread: vi.fn(() => Promise.resolve([])),
  pinThread: vi.fn(() => Promise.resolve()),
  deleteThread: vi.fn(() => Promise.resolve()),
  streamChat: vi.fn(() => Promise.resolve()),
  retryChat: vi.fn(() => Promise.resolve()),
}))

const api = await import('../api')

/** Make `streamChat` deliver these events, then finish. */
function replying(...events: ChatEvent[]) {
  vi.mocked(api.streamChat).mockImplementation(
    async (_message, _threadId, onEvent) => {
      for (const event of events) onEvent(event)
    })
}

/** Make `retryChat` deliver these events, then finish. */
function retrying(...events: ChatEvent[]) {
  vi.mocked(api.retryChat).mockImplementation(async (_threadId, onEvent) => {
    for (const event of events) onEvent(event)
  })
}

/** One answered turn, to retry. */
async function answered(result: { current: ReturnType<typeof useChat> }) {
  replying({ type: 'start', thread_id: 'held' },
           { type: 'token', text: 'The first answer.' })
  await act(() => result.current.send('Prone?'))
}

beforeEach(() => {
  vi.mocked(api.listThreads).mockResolvedValue([])
  vi.mocked(api.streamChat).mockResolvedValue(undefined)
  vi.mocked(api.retryChat).mockResolvedValue(undefined)
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

  it('given what the turn cost, when it arrives, then it is on the answer', async () => {
    // Given a turn that reports its tokens
    replying({ type: 'usage', input: 17_790, output: 450, total: 18_240,
               calls: 5 })
    const { result } = renderHook(() => useChat())

    // When it runs
    await act(() => result.current.send('Prone?'))

    // Then the counts are on the answer, without the event's own type
    expect(result.current.messages[1].usage).toEqual(
      { input: 17_790, output: 450, total: 18_240, calls: 5 })
  })

  it('given a failed turn, when the error arrives, then it is the answer', async () => {
    // Given a turn the model could not answer
    replying({ type: 'error', message: 'The Gemini quota is spent' })
    const { result } = renderHook(() => useChat())

    // When it runs
    await act(() => result.current.send('Prone?'))

    // Then the error is on the message, with nothing beside it
    expect(result.current.messages[1].error).toContain('quota')
    expect(result.current.messages[1].content).toBe('')
  })

  it('given a request that fails, when sent, then the failure is the answer', async () => {
    // Given a server that refuses the turn before it starts
    vi.mocked(api.streamChat).mockRejectedValueOnce(
      new Error('GOOGLE_API_KEY is not set'))
    const { result } = renderHook(() => useChat())

    // When a question is sent
    await act(() => result.current.send('Prone?'))

    // Then the reason is where the answer would be, and the turn is over
    expect(result.current.messages[1].error).toContain('GOOGLE_API_KEY is not set')
    expect(result.current.streaming).toBe(false)
  })

  it('given a turn in flight, when stopped, then no error is shown', async () => {
    // Given a turn that runs until it is aborted, as fetch does
    vi.mocked(api.streamChat).mockImplementationOnce(
      (_message, _threadId, _onEvent, signal) => new Promise((_, reject) =>
        signal!.addEventListener('abort', () =>
          reject(new DOMException('The user aborted a request.', 'AbortError')))))
    const { result } = renderHook(() => useChat())
    let sent: Promise<void> = Promise.resolve()
    act(() => { sent = result.current.send('Prone?') })

    // When the reader stops it
    await act(async () => { result.current.stop(); await sent })

    // Then stopping is not reported as a failure
    expect(result.current.messages[1].error).toBeUndefined()
    expect(result.current.streaming).toBe(false)
  })
})

describe('open', () => {
  it('given a stored conversation, when opened, then it is fetched, not cached', async () => {
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

  it('given a thread that will not load, when opened, then the next question stays put', async () => {
    // Given a conversation on screen, and another that has gone
    const { result } = renderHook(() => useChat())
    await answered(result)
    vi.mocked(api.loadThread).mockRejectedValueOnce(new Error("no thread 'gone'"))
    vi.mocked(api.listThreads).mockClear()

    // When the gone one is opened
    await act(() => result.current.open('gone'))

    // Then the screen and the thread a question would join still agree
    expect(result.current.threadId).toBe('held')
    expect(result.current.messages[1].content).toBe('The first answer.')
    // And the list is refetched, so the gone thread leaves it
    expect(api.listThreads).toHaveBeenCalled()
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

  it('given a new conversation, when its turn starts, then it is listed untitled at once', async () => {
    // Given a turn that starts and never finishes
    vi.mocked(api.streamChat).mockImplementation(async (_m, _t, onEvent) => {
      onEvent({ type: 'start', thread_id: 'minted' })
      await new Promise(() => {})
    })
    const { result } = renderHook(() => useChat())
    await waitFor(() => expect(api.listThreads).toHaveBeenCalled())

    // When a question is sent
    act(() => void result.current.send('Can a Prone creature stand?'))

    // Then the thread is listed while the answer is still streaming
    await waitFor(() => expect(result.current.threads).toHaveLength(1))
    expect(result.current.threads[0]).toMatchObject(
      { thread_id: 'minted', title: '', pinned: false })
    expect(result.current.streaming).toBe(true)
  })

  it('given a new conversation, when its title arrives, then the row takes it mid-turn', async () => {
    // Given a turn that starts, is titled, and never finishes
    vi.mocked(api.streamChat).mockImplementation(async (_m, _t, onEvent) => {
      onEvent({ type: 'start', thread_id: 'minted' })
      onEvent({ type: 'title', thread_id: 'minted', title: 'Standing from Prone' })
      await new Promise(() => {})
    })
    const { result } = renderHook(() => useChat())
    await waitFor(() => expect(api.listThreads).toHaveBeenCalled())

    // When a question is sent
    act(() => void result.current.send('Can a Prone creature stand?'))

    // Then the row is titled before the answer ends
    await waitFor(() =>
      expect(result.current.threads[0]?.title).toBe('Standing from Prone'))
    expect(result.current.streaming).toBe(true)
  })

  it('given a listed conversation, when another turn starts, then it is not listed twice', async () => {
    // Given a thread the server already lists
    const listed = { thread_id: 'held', title: 'Prone rules', pinned: false,
                     updated_at: null, messages: 1 }
    vi.mocked(api.listThreads).mockResolvedValue([listed])
    vi.mocked(api.streamChat).mockImplementation(async (_m, _t, onEvent) => {
      onEvent({ type: 'start', thread_id: 'held' })
      await new Promise(() => {})
    })
    const { result } = renderHook(() => useChat())
    await waitFor(() => expect(result.current.threads).toEqual([listed]))

    // When a follow-up starts
    act(() => void result.current.send('And standing up?'))
    await waitFor(() => expect(result.current.threadId).toBe('held'))

    // Then the list keeps the server's row as it was
    expect(result.current.threads).toEqual([listed])
  })
})

describe('retry', () => {
  it('given an answered turn, when retried, then the answer is replaced', async () => {
    // Given an answered conversation
    const { result } = renderHook(() => useChat())
    await answered(result)
    retrying({ type: 'token', text: 'The second answer.' })

    // When the turn is retried
    await act(() => result.current.retry())

    // Then the question stands and the answer under it is the new one
    expect(result.current.messages.map((m) => m.role))
      .toEqual(['user', 'assistant'])
    expect(result.current.messages[0].content).toBe('Prone?')
    expect(result.current.messages[1].content).toBe('The second answer.')
    expect(api.retryChat).toHaveBeenCalledWith(
      'held', expect.any(Function), expect.any(AbortSignal))
  })

  it('given a turn that failed, when retried, then the error goes with it', async () => {
    // Given a turn the model could not answer
    const { result } = renderHook(() => useChat())
    replying({ type: 'start', thread_id: 'held' },
             { type: 'error', message: 'The Gemini quota is spent.' })
    await act(() => result.current.send('Prone?'))
    retrying({ type: 'token', text: 'A Prone creature…' })

    // When it is retried
    await act(() => result.current.retry())

    // Then nothing of the failure is left under the question
    expect(result.current.messages[1].error).toBeUndefined()
    expect(result.current.messages[1].content).toBe('A Prone creature…')
  })

  it('given a conversation the server never saw, when retried, then nothing happens', async () => {
    // Given a thread that was never minted
    const { result } = renderHook(() => useChat())

    // When a retry is asked for
    await act(() => result.current.retry())

    // Then there was nothing to rewind
    expect(api.retryChat).not.toHaveBeenCalled()
    expect(result.current.messages).toEqual([])
  })

  it('given a turn in flight, when retried, then it is ignored', async () => {
    // Given an answered conversation with a second turn under way
    const { result } = renderHook(() => useChat())
    await answered(result)
    vi.mocked(api.streamChat).mockImplementation(() => new Promise(() => {}))
    act(() => void result.current.send('Restrained?'))
    await waitFor(() => expect(result.current.streaming).toBe(true))

    // When a retry is asked for
    await act(() => result.current.retry())

    // Then the turn being written was not rewound under itself
    expect(api.retryChat).not.toHaveBeenCalled()
    expect(result.current.messages).toHaveLength(4)
  })
})
