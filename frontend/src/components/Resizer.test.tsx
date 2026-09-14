/**
 * The drag handles either side of the conversation.
 *
 * How wide the thread list and the page facsimile need to be are questions
 * about the reader's screen and eyes, so both are controls rather than
 * constants — and the clamping is what keeps one edge from eating the other.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  MAX_SIDEBAR, MIN_PANEL, MIN_SIDEBAR, Resizer, clampWidth, defaultPanel,
} from './Resizer'

/** jsdom defaults to 1024×768; set it where a test needs a wider desk. */
function windowWidth(width: number) {
  Object.defineProperty(window, 'innerWidth', { value: width,
                                                configurable: true })
}

beforeEach(() => windowWidth(1600))

describe('clampWidth', () => {
  it('given a width in range, when clamped, then it is kept', () => {
    // Given a comfortable sidebar on a wide window
    // When it is clamped
    // Then the reader's choice stands
    expect(clampWidth('sidebar', 300, 400)).toBe(300)
  })

  it('given a width below the minimum, when clamped, then the minimum wins', () => {
    // Given a sidebar dragged past useful
    // When it is clamped
    // Then a thread title still has a line to sit on
    expect(clampWidth('sidebar', 40, 400)).toBe(MIN_SIDEBAR)
    expect(clampWidth('panel', 40, 200)).toBe(MIN_PANEL)
  })

  it('given a sidebar dragged very wide, when clamped, then its own maximum applies', () => {
    /** A thread title is one line of text; past this it is just whitespace. */
    // Given a sidebar dragged across the desk
    // When it is clamped
    // Then it stops where the text does
    expect(clampWidth('sidebar', 900, 400)).toBe(MAX_SIDEBAR)
  })

  it('given a wide opposite edge, when clamped, then the conversation keeps its room', () => {
    /**
     * The two share a window, so neither can be clamped alone: widening the
     * panel while the sidebar is wide would leave nothing in between.
     */
    // Given a 1000px window with a 400px panel already taken
    windowWidth(1000)

    // When the sidebar is dragged wide
    const width = clampWidth('sidebar', 900, 400)

    // Then what is left of the window is still readable
    expect(width + 400).toBeLessThanOrEqual(1000 - 420)
  })

  it('given a very narrow window, when clamped, then the minimum still wins', () => {
    /** `max` can fall below `min`, and the layout's media query takes over. */
    // Given a window too small for both edges at once
    windowWidth(500)

    // When the panel is clamped
    // Then it is its minimum rather than a negative width
    expect(clampWidth('panel', 600, 300)).toBe(MIN_PANEL)
  })
})

describe('defaultPanel', () => {
  it('given a screen never seen before, when opened, then the width is proportional', () => {
    /**
     * The page is rendered *to fit the panel*, so the panel's width is the
     * reading size; a fixed default is a thumbnail on one screen and half
     * the desk on another.
     */
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
    // Given the sidebar's handle
    render(<Resizer edge="sidebar" width={300} other={400} onResize={() => {}} />)

    // When it is found by role
    const handle = screen.getByRole('separator', {
      name: 'Resize the conversation list' })

    // Then it reports which way it moves and where it is
    expect(handle).toHaveAttribute('aria-orientation', 'vertical')
    expect(handle).toHaveAttribute('aria-valuenow', '300')
  })

  it('given the sidebar handle, when dragged right, then the sidebar widens', () => {
    // Given a sidebar being dragged
    const onResize = vi.fn()
    render(<Resizer edge="sidebar" width={300} other={400} onResize={onResize} />)

    // When the pointer moves right of where it started
    fireEvent.pointerDown(screen.getByRole('separator'))
    fireEvent.pointerMove(window, { clientX: 360 })

    // Then the sidebar grows rightwards from x=0
    expect(onResize).toHaveBeenLastCalledWith(360)
  })

  it('given the panel handle, when dragged left, then the panel widens', () => {
    /** The only difference between the two edges is which way wider points. */
    // Given the panel's handle on a 1600px window
    const onResize = vi.fn()
    render(<Resizer edge="panel" width={600} other={200} onResize={onResize} />)

    // When the pointer moves left
    fireEvent.pointerDown(screen.getByRole('separator'))
    fireEvent.pointerMove(window, { clientX: 900 })

    // Then the panel grows leftwards from the right-hand edge
    expect(onResize).toHaveBeenLastCalledWith(700)
  })

  it('given a drag in progress, when the pointer leaves the handle, then it continues', () => {
    /** A pointer routinely leaves a 13px target mid-drag. */
    // Given a drag that started on the handle
    const onResize = vi.fn()
    render(<Resizer edge="sidebar" width={300} other={400} onResize={onResize} />)
    fireEvent.pointerDown(screen.getByRole('separator'))

    // When the pointer moves far away from it, on the window
    fireEvent.pointerMove(window, { clientX: 250 })

    // Then the drag is still being tracked
    expect(onResize).toHaveBeenLastCalledWith(250)
  })

  it('given a drag, when the pointer is released, then it stops tracking', () => {
    // Given a finished drag
    const onResize = vi.fn()
    render(<Resizer edge="sidebar" width={300} other={400} onResize={onResize} />)
    fireEvent.pointerDown(screen.getByRole('separator'))
    fireEvent.pointerUp(window)
    onResize.mockClear()

    // When the pointer moves again
    fireEvent.pointerMove(window, { clientX: 250 })

    // Then nothing follows it any more
    expect(onResize).not.toHaveBeenCalled()
  })

  it('given a keyboard, when the arrow keys are pressed, then the divider moves', () => {
    /** Dragging is not the only way to move a divider. */
    // Given the sidebar's handle with focus
    const onResize = vi.fn()
    render(<Resizer edge="sidebar" width={300} other={400} onResize={onResize} />)
    const handle = screen.getByRole('separator')

    // When the arrows are pressed
    fireEvent.keyDown(handle, { key: 'ArrowRight' })
    fireEvent.keyDown(handle, { key: 'ArrowLeft' })

    // Then it steps wider and then narrower
    expect(onResize).toHaveBeenNthCalledWith(1, 330)
    expect(onResize).toHaveBeenNthCalledWith(2, 270)
  })

  it('given the panel handle, when the arrow keys are pressed, then wider points the other way', () => {
    // Given the panel's handle
    const onResize = vi.fn()
    render(<Resizer edge="panel" width={600} other={200} onResize={onResize} />)

    // When left is pressed
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'ArrowLeft' })

    // Then the panel widens, because that is the way it grows
    expect(onResize).toHaveBeenCalledWith(630)
  })

  it('given another key, when pressed, then nothing moves', () => {
    // Given the handle
    const onResize = vi.fn()
    render(<Resizer edge="sidebar" width={300} other={400} onResize={onResize} />)

    // When an unrelated key is pressed
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'Enter' })

    // Then the divider stays where it is
    expect(onResize).not.toHaveBeenCalled()
  })
})
