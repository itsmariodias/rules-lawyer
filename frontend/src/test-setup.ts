/**
 * What every test file gets before it runs.
 *
 * jsdom implements neither the observers the layout code measures with nor
 * the canvas pdf.js renders into, so both are stubbed here rather than in
 * each test that happens to mount a component using them.
 */

import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, beforeEach, vi } from 'vitest'

class NoopObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

/**
 * jsdom lays nothing out, so an observer reporting the real element would
 * report nothing: the graph would be laid out in a 0×0 panel and draw no
 * nodes at all.  This one answers with a plausible panel instead.
 */
class SizedObserver {
  private readonly callback: ResizeObserverCallback

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }

  observe(target: Element) {
    const contentRect = { width: 900, height: 700, top: 0, left: 0,
                          right: 900, bottom: 700, x: 0, y: 0 }
    this.callback([{ target, contentRect } as ResizeObserverEntry],
                  this as unknown as ResizeObserver)
  }

  unobserve() {}
  disconnect() {}
}

// Assigned rather than defaulted: jsdom ships a ResizeObserver that never
// fires, because it lays nothing out to observe.
globalThis.ResizeObserver = SizedObserver as never
globalThis.IntersectionObserver ??= NoopObserver as never

// The simulation publishes a position per frame; without this it never runs
// and without a bound it would never stop inside a test.
globalThis.requestAnimationFrame ??= ((callback: FrameRequestCallback) =>
  setTimeout(() => callback(performance.now()), 16) as unknown as number) as never
globalThis.cancelAnimationFrame ??= ((handle: number) =>
  clearTimeout(handle)) as never

beforeEach(() => {
  // Nothing under test may reach the network by accident: a test that wants
  // a response says so.
  vi.stubGlobal('fetch', vi.fn(() =>
    Promise.reject(new Error('unexpected fetch in a test'))))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  localStorage.clear()
})
