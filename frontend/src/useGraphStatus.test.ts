import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from './api'
import { RETRY_MS, useGraphStatus } from './useGraphStatus'

vi.mock('./api', () => ({ graphStatus: vi.fn() }))

beforeEach(() => {
  vi.useFakeTimers()
  vi.mocked(api.graphStatus).mockReset()
})

afterEach(() => vi.useRealTimers())

/** Let the pending request resolve.  `waitFor` polls on real timers. */
const settle = () => act(async () => { await vi.advanceTimersByTimeAsync(0) })
const wait = (ms: number) =>
  act(async () => { await vi.advanceTimersByTimeAsync(ms) })

describe('useGraphStatus', () => {
  it('given a loaded graph, when asked, then it reports the connection', async () => {
    // Given a database that is up and holds the book
    vi.mocked(api.graphStatus).mockResolvedValue('connected')

    // When the hook runs
    const { result } = renderHook(() => useGraphStatus())

    // Then nothing is claimed until the answer is in, and then it is
    expect(result.current).toBe('checking')
    await settle()
    expect(result.current).toBe('connected')
  })

  it('given a graph that is up but empty, when asked, then it says empty', async () => {
    // Given a database nothing has been loaded into
    vi.mocked(api.graphStatus).mockResolvedValue('empty')

    // When the hook runs
    const { result } = renderHook(() => useGraphStatus())
    await settle()

    // Then the emptiness is the status, not a detail behind it
    expect(result.current).toBe('empty')
  })

  it('given a connected graph, when time passes, then it is not asked again', async () => {
    // Given a database that answered once
    vi.mocked(api.graphStatus).mockResolvedValue('connected')
    const { result } = renderHook(() => useGraphStatus())
    await settle()
    expect(result.current).toBe('connected')
    const asked = vi.mocked(api.graphStatus).mock.calls.length

    // When a retry interval goes by
    await wait(RETRY_MS * 2)

    // Then nothing was polled: there is nothing left to watch for
    expect(api.graphStatus).toHaveBeenCalledTimes(asked)
  })

  it('given a database that comes up late, when it does, then the label follows', async () => {
    // Given a database that is down when the app starts
    vi.mocked(api.graphStatus).mockResolvedValue('unreachable')
    const { result } = renderHook(() => useGraphStatus())
    await settle()
    expect(result.current).toBe('unreachable')

    // When it comes up and a retry falls due
    vi.mocked(api.graphStatus).mockResolvedValue('connected')
    await wait(RETRY_MS)

    // Then the footer stops lying about it
    expect(result.current).toBe('connected')
  })
})
