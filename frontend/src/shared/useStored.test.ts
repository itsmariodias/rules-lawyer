import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useStored, useTheme } from './useStored'

describe('useStored', () => {
  it('given nothing stored, when read, then the fallback is used', () => {
    // Given empty storage
    // When the hook is rendered
    const { result } = renderHook(() => useStored('width', 320))

    // Then the fallback is what the reader sees
    expect(result.current[0]).toBe(320)
  })

  it('given a stored value, when read, then it wins over the fallback', () => {
    // Given a value written by an earlier session
    localStorage.setItem('width', '640')

    // When the hook is rendered
    const { result } = renderHook(() => useStored('width', 320))

    // Then the remembered width is used
    expect(result.current[0]).toBe(640)
  })

  it('given a new value, when set, then it is written back', () => {
    // Given the hook
    const { result } = renderHook(() => useStored('width', 320))

    // When the value changes
    act(() => result.current[1](480))

    // Then it survives into the next session
    expect(result.current[0]).toBe(480)
    expect(localStorage.getItem('width')).toBe('480')
  })

  it('given an object, when stored, then it round-trips as JSON', () => {
    // Given a hook holding something other than a number
    const { result } = renderHook(() =>
      useStored('tab', { tab: 'page' as const }))

    // When it is changed
    act(() => result.current[1]({ tab: 'graph' as never }))

    // Then it is read back as the value, not as its string
    expect(JSON.parse(localStorage.getItem('tab') ?? '')).toEqual({ tab: 'graph' })
  })

  it('given storage that throws on read, when rendered, then the fallback is used', () => {
    // Given a browser set to block site data
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('access denied')
    })

    // When the hook is rendered
    const { result } = renderHook(() => useStored('width', 320))

    // Then the page renders rather than failing over a preference
    expect(result.current[0]).toBe(320)
  })

  it('given storage that throws on write, when set, then nothing is raised', () => {
    // Given a browser that refuses to store anything
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota exceeded')
    })
    const { result } = renderHook(() => useStored('width', 320))

    // When the value changes
    // Then the state still moves, and the failure is not the reader's problem
    expect(() => act(() => result.current[1](480))).not.toThrow()
    expect(result.current[0]).toBe(480)
  })

  it('given unreadable JSON, when read, then the fallback is used', () => {
    // Given a value an older version wrote in another shape
    localStorage.setItem('width', 'not json')

    // When the hook is rendered
    const { result } = renderHook(() => useStored('width', 320))

    // Then it falls back rather than throwing on parse
    expect(result.current[0]).toBe(320)
  })
})

describe('useTheme', () => {
  it('given no choice, when rendered, then the machine decides', () => {
    // Given a document carrying an earlier choice
    document.documentElement.dataset.theme = 'dark'

    // When the theme is rendered as system
    renderHook(() => useTheme())

    // Then nothing is stamped on the root
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })

  it('given a chosen theme, when set, then it is stamped on the document', () => {
    // Given the hook
    const { result } = renderHook(() => useTheme())

    // When dark is chosen
    act(() => result.current[1]('dark'))

    // Then the root carries it, for the CSS to key off
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('given a chosen theme, when the page reloads, then it is remembered', () => {
    // Given a theme chosen in an earlier session
    localStorage.setItem('theme', '"light"')

    // When the hook is rendered again
    const { result } = renderHook(() => useTheme())

    // Then the choice survived the reload
    expect(result.current[0]).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })
})
