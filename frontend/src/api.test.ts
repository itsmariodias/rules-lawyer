/**
 * The browser's half of the SSE contract.
 *
 * The plain calls are thin, so what is worth testing is the framing:
 * `fetch` rather than `EventSource` means events arrive in chunks whose
 * boundaries land anywhere, and a frame split across two reads must not be
 * lost or parsed twice.
 */

import { describe, expect, it, vi } from 'vitest'

import {
  deleteThread, listThreads, loadNeighbourhood, loadSource, loadThread,
  pinThread, streamChat, type ChatEvent,
} from './api'

/** A `fetch` answering one JSON body. */
function answering(body: unknown, ok = true, status = 200) {
  const response = {
    ok, status, statusText: ok ? 'OK' : 'Not Found',
    json: () => Promise.resolve(body),
  }
  const stub = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve(response as unknown as Response))
  vi.stubGlobal('fetch', stub)
  return stub
}

/** A `fetch` whose body streams the given chunks, as the server would. */
function streaming(chunks: string[]) {
  const encoder = new TextEncoder()
  const queue = chunks.map((chunk) => encoder.encode(chunk))
  const body = {
    getReader: () => ({
      read: () => Promise.resolve(
        queue.length ? { done: false, value: queue.shift() }
                     : { done: true, value: undefined }),
    }),
  }
  const stub = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve({ ok: true, status: 200, body } as unknown as Response))
  vi.stubGlobal('fetch', stub)
  return stub
}

const frame = (event: object) => `data: ${JSON.stringify(event)}\n\n`

describe('listThreads', () => {
  it('given stored conversations, when listed, then the array is unwrapped', async () => {
    // Given a server holding one conversation
    answering({ threads: [{ thread_id: 'a', title: 'Prone', pinned: false }] })

    // When the threads are listed
    const threads = await listThreads()

    // Then the caller gets the list, not the envelope around it
    expect(threads).toHaveLength(1)
    expect(threads[0].thread_id).toBe('a')
  })

  it('given a failing request, when listed, then the status is raised', async () => {
    // Given a server that refuses
    answering(null, false, 503)

    // When the threads are listed
    // Then the failure carries its status, for the caller to show or swallow
    await expect(listThreads()).rejects.toThrow('503')
  })
})

describe('loadThread', () => {
  it('given a thread id, when loaded, then its messages come back', async () => {
    // Given a stored conversation
    const stub = answering({ messages: [{ role: 'user', content: 'Prone?' }] })

    // When it is loaded
    const messages = await loadThread('abc')

    // Then it was fetched by id, and the turns are returned
    expect(stub).toHaveBeenCalledWith('/api/chat/threads/abc')
    expect(messages[0].content).toBe('Prone?')
  })
})

describe('pinThread', () => {
  it('given a conversation, when pinned, then the flag is sent as JSON', async () => {
    // Given a server that accepts the pin
    const stub = answering(null)

    // When a conversation is pinned
    await pinThread('abc', true)

    // Then the request says which and whether
    const [url, init] = stub.mock.calls[0]
    expect(url).toBe('/api/chat/threads/abc/pin')
    expect(init!.method).toBe('PUT')
    expect(init!.body).toBe(JSON.stringify({ pinned: true }))
  })

  it('given a thread that is gone, when pinned, then the failure surfaces', async () => {
    // Given a server that answers 404
    answering(null, false, 404)

    // When it is pinned
    // Then the caller is told rather than left believing it worked
    await expect(pinThread('gone', true)).rejects.toThrow('404')
  })
})

describe('deleteThread', () => {
  it('given a conversation, when deleted, then the request is a DELETE', async () => {
    // Given a server that accepts the delete
    const stub = answering(null)

    // When a conversation is deleted
    await deleteThread('abc')

    // Then it is addressed by id, with no body
    expect(stub).toHaveBeenCalledWith('/api/chat/threads/abc',
                                      { method: 'DELETE' })
  })
})

describe('loadSource', () => {
  it('given a citation, when loaded, then no context is asked for by default', async () => {
    // Given a cited section
    const stub = answering({ section_id: '11.2.114', text: 'Prone…' })

    // When it is loaded
    await loadSource('11.2.114')

    // Then the slice is exactly the section
    expect(stub).toHaveBeenCalledWith('/api/source/11.2.114?context=0')
  })

  it('given context, when loaded, then it is passed to the server', async () => {
    // Given a reader who wants the surroundings
    const stub = answering({ section_id: '11.2.114', text: 'Prone…' })

    // When the source is loaded with context
    await loadSource('11.2.114', 400)

    // Then the widened slice is requested
    expect(stub).toHaveBeenCalledWith('/api/source/11.2.114?context=400')
  })
})

describe('loadNeighbourhood', () => {
  it('given a citation, when loaded, then the seed is the section', async () => {
    // Given a cited section
    const stub = answering({ root: 'x', nodes: [], edges: [], truncated: [] })

    // When its neighbourhood is loaded
    await loadNeighbourhood({ section: '11.2.114' }, 1)

    // Then the section names the seed, at the asked-for depth
    expect(stub).toHaveBeenCalledWith(
      '/api/neighbourhood?section=11.2.114&depth=1')
  })

  it('given a drawn node, when expanded, then it is the seed instead', async () => {
    /**
     * A citation names a section, but the interesting neighbours are not all
     * sections, so an expansion names the node it was already shown.
     */
    // Given a node from an earlier answer
    const stub = answering({ root: 'x', nodes: [], edges: [], truncated: [] })

    // When it is expanded
    await loadNeighbourhood({ node: '4:abc:1' }, 2)

    // Then the node names the seed
    expect(stub.mock.calls[0][0]).toContain('node=4')
  })

  it('given a wider fan, when loaded, then it is sent; otherwise it is left out', async () => {
    /**
     * The server samples deterministically, so asking again for the same fan
     * returns the same neighbours; only a wider one shows anything new.
     */
    // Given a hub asked for more
    const stub = answering({ root: 'x', nodes: [], edges: [], truncated: [] })

    // When it is loaded with and without a fan
    await loadNeighbourhood({ node: 'n' }, 1, 16)
    await loadNeighbourhood({ node: 'n' }, 1)

    // Then only the widened request carries one, leaving the server's default
    expect(stub.mock.calls[0][0]).toContain('fan=16')
    expect(stub.mock.calls[1][0]).not.toContain('fan')
  })
})

describe('streamChat', () => {
  it('given whole frames, when streamed, then each becomes one event', async () => {
    // Given a server sending three complete frames
    streaming([
      frame({ type: 'start', thread_id: 'abc' }),
      frame({ type: 'token', text: 'Prone ' }),
      frame({ type: 'done', thread_id: 'abc' }),
    ])
    const seen: ChatEvent[] = []

    // When the turn is streamed
    await streamChat('Prone?', null, (event) => seen.push(event))

    // Then every event arrived, in order
    expect(seen.map((event) => event.type)).toEqual(['start', 'token', 'done'])
  })

  it('given a frame split across two chunks, when streamed, then it is not lost', () => {
    /**
     * A chunk boundary can land anywhere, so the tail of a chunk is held
     * back until its blank line arrives.
     */
    // Given one frame arriving in two pieces
    streaming(['data: {"type":"tok', 'en","text":"Prone"}\n\n'])
    const seen: ChatEvent[] = []

    // When the turn is streamed
    return streamChat('Prone?', null, (event) => seen.push(event))
      .then(() => {
        // Then the halves were rejoined into one event
        expect(seen).toEqual([{ type: 'token', text: 'Prone' }])
      })
  })

  it('given two frames in one chunk, when streamed, then both are read', async () => {
    // Given a chunk carrying two complete frames
    streaming([frame({ type: 'token', text: 'a' })
               + frame({ type: 'token', text: 'b' })])
    const seen: ChatEvent[] = []

    // When the turn is streamed
    await streamChat('Prone?', null, (event) => seen.push(event))

    // Then neither was swallowed by the other
    expect(seen).toHaveLength(2)
  })

  it('given a thread id, when streamed, then the turn joins that conversation', async () => {
    // Given a conversation the browser already holds
    const stub = streaming([frame({ type: 'done', thread_id: 'held' })])

    // When a turn is sent under it
    await streamChat('and at 5th level?', 'held', () => {})

    // Then the id and the message are in the body
    const init = stub.mock.calls[0][1]!
    expect(JSON.parse(String(init.body))).toEqual({
      message: 'and at 5th level?', thread_id: 'held',
    })
  })

  it('given a refused request, when streamed, then the status is raised', async () => {
    // Given a server that refuses the turn
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(
      { ok: false, status: 500, statusText: 'Server Error',
        body: null } as unknown as Response)))

    // When the turn is streamed
    // Then the caller can show the failure rather than waiting on a stream
    await expect(streamChat('Prone?', null, () => {}))
      .rejects.toThrow('500')
  })
})
