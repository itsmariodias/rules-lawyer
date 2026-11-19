import { beforeEach, describe, expect, it } from 'vitest'

import { showThread, threadOf, threadPath } from './route'

beforeEach(() => window.history.replaceState(null, '', '/'))

describe('threadPath', () => {
  it('given a thread id, when made a path, then it is under /chat', () => {
    // Given a stored thread's id
    // When it is made a path
    // Then the path names it
    expect(threadPath('3f2a')).toBe('/chat/3f2a')
  })

  it('given no thread, when made a path, then it is the new chat at the root', () => {
    // Given no thread
    // When it is made a path
    // Then it is the root
    expect(threadPath(null)).toBe('/')
  })
})

describe('threadOf', () => {
  it('given a thread path, when read, then its id comes back', () => {
    // Given the path of an id that needed escaping
    const path = threadPath('a b')

    // When it is read
    // Then the id is the one written
    expect(threadOf(path)).toBe('a b')
  })

  it.each(['/', '/chat/', '/chat/a/b', '/elsewhere/a'])(
    'given %s, when read, then it names no thread', (path) => {
      // Given a path that is not one thread's
      // When it is read
      // Then there is no thread to open
      expect(threadOf(path)).toBeNull()
    })
})

describe('showThread', () => {
  it('given a push, when shown, then Back has somewhere to return to', () => {
    // Given the new chat at the root
    const before = window.history.length

    // When a thread is pushed
    showThread('abc', 'push')

    // Then the bar shows it, on a new history entry
    expect(window.location.pathname).toBe('/chat/abc')
    expect(window.history.length).toBe(before + 1)
  })

  it('given a replace, when shown, then no history entry is added', () => {
    // Given the new chat at the root
    const before = window.history.length

    // When a thread replaces it
    showThread('abc', 'replace')

    // Then the bar shows it, in the same entry
    expect(window.location.pathname).toBe('/chat/abc')
    expect(window.history.length).toBe(before)
  })

  it('given the thread already shown, when pushed again, then nothing is added', () => {
    // Given a thread in the bar
    showThread('abc', 'push')
    const before = window.history.length

    // When it is pushed again
    showThread('abc', 'push')

    // Then the history is unchanged
    expect(window.history.length).toBe(before)
  })
})
