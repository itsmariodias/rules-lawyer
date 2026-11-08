import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MIN_PANEL, Resizer, SIDEBAR, clampWidth, defaultPanel } from './Resizer'

/** jsdom defaults to 1024×768. */
function windowWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', { value: width,
                                                configurable: true })
}

beforeEach(() => windowWidth(1600))

describe('clampWidth', () => {
  it('given a width in range, when clamped, then it is kept', () => {
    // Given a comfortable panel on a wide window
    // When it is clamped
    // Then the reader's choice stands
    expect(clampWidth(600, SIDEBAR)).toBe(600)
  })

  it('given a width below the minimum, when clamped, then the minimum wins', () => {
    // Given a panel dragged past useful
    // When it is clamped
    // Then a column of the book still fits
    expect(clampWidth(40, SIDEBAR)).toBe(MIN_PANEL)
  })

  it('given an open thread list, when clamped, then the conversation keeps its room', () => {
    // Given a 1512px window with the thread list open
    windowWidth(1512)

    // When the panel is dragged wide
    const width = clampWidth(1000, SIDEBAR)

    // Then what is left of the window is still readable
    expect(width).toBe(1512 - SIDEBAR - 420)
  })

  it('given a hidden thread list, when clamped, then the panel may take its room', () => {
    // Given the same window with the thread list hidden
    windowWidth(1512)

    // When the panel is dragged wide
    // Then only the conversation limits it
    expect(clampWidth(1000, 0)).toBe(1000)
  })

  it('given a very narrow window, when clamped, then the minimum still wins', () => {
    // Given a window too small for the panel and the conversation at once
    windowWidth(500)

    // When the panel is clamped
    // Then it is its minimum rather than a negative width
    expect(clampWidth(600, SIDEBAR)).toBe(MIN_PANEL)
  })
})

describe('defaultPanel', () => {
  it('given a screen never seen before, when opened, then the width is proportional', () => {
    // Given a wide display
    windowWidth(2000)

    // When the panel opens for the first time
    // Then it takes about half the window, within its own bounds
    expect(defaultPanel()).toBe(1000)
  })

  it('given a laptop, when opened, then the conversation is still usable', () => {
    // Given a smaller display
    windowWidth(1280)

    // When the panel opens
    const width = defaultPanel()

    // Then it is readable and leaves the conversation room
    expect(width).toBeGreaterThanOrEqual(MIN_PANEL)
    expect(1280 - width).toBeGreaterThanOrEqual(420)
  })
})

describe('Resizer', () => {
  it('given a handle, when read by an assistive technology, then it is a separator', () => {
    // Given the panel's handle
    render(<Resizer width={600} sidebar={SIDEBAR} onResize={() => {}} />)

    // When it is found by role
    const handle = screen.getByRole('separator', { name: 'Resize the page panel' })

    // Then it reports which way it moves and where it is
    expect(handle).toHaveAttribute('aria-orientation', 'vertical')
    expect(handle).toHaveAttribute('aria-valuenow', '600')
  })

  it('given the handle, when dragged left, then the panel widens', () => {
    // Given the panel's handle on a 1600px window
    const onResize = vi.fn()
    render(<Resizer width={600} sidebar={200} onResize={onResize} />)

    // When the pointer moves left
    fireEvent.pointerDown(screen.getByRole('separator'))
    fireEvent.pointerMove(window, { clientX: 900 })

    // Then the panel grows leftwards from the right-hand edge
    expect(onResize).toHaveBeenLastCalledWith(700)
  })

  it('given a drag in progress, when the pointer leaves the handle, then it continues', () => {
    // Given a drag that started on the handle
    const onResize = vi.fn()
    render(<Resizer width={600} sidebar={200} onResize={onResize} />)
    fireEvent.pointerDown(screen.getByRole('separator'))

    // When the pointer moves far away from it, on the window
    fireEvent.pointerMove(window, { clientX: 1100 })

    // Then the drag is still being tracked
    expect(onResize).toHaveBeenLastCalledWith(500)
  })

  it('given a drag, when the pointer is released, then it stops tracking', () => {
    // Given a finished drag
    const onResize = vi.fn()
    render(<Resizer width={600} sidebar={200} onResize={onResize} />)
    fireEvent.pointerDown(screen.getByRole('separator'))
    fireEvent.pointerUp(window)
    onResize.mockClear()

    // When the pointer moves again
    fireEvent.pointerMove(window, { clientX: 900 })

    // Then nothing follows it any more
    expect(onResize).not.toHaveBeenCalled()
  })

  it('given a keyboard, when the arrow keys are pressed, then the divider moves', () => {
    // Given the panel's handle with focus
    const onResize = vi.fn()
    render(<Resizer width={600} sidebar={200} onResize={onResize} />)
    const handle = screen.getByRole('separator')

    // When the arrows are pressed
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })
    fireEvent.keyDown(handle, { key: 'ArrowRight' })

    // Then left widens the panel, because that is the way it grows
    expect(onResize).toHaveBeenNthCalledWith(1, 630)
    expect(onResize).toHaveBeenNthCalledWith(2, 570)
  })

  it('given another key, when pressed, then nothing moves', () => {
    // Given the handle
    const onResize = vi.fn()
    render(<Resizer width={600} sidebar={200} onResize={onResize} />)

    // When an unrelated key is pressed
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'Enter' })

    // Then the divider stays where it is
    expect(onResize).not.toHaveBeenCalled()
  })
})
