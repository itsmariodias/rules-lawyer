import { describe, expect, it, vi } from 'vitest'

import { followPointer } from './pointer'

const move = () => window.dispatchEvent(new MouseEvent('pointermove'))

describe('followPointer', () => {
  it('given a drag, when the pointer moves, then every move is followed', () => {
    // Given a drag in progress
    const onMove = vi.fn()
    followPointer(onMove)

    // When the pointer moves twice
    move()
    move()

    // Then both moves were seen
    expect(onMove).toHaveBeenCalledTimes(2)
    window.dispatchEvent(new MouseEvent('pointerup'))
  })

  it('given a drag, when the pointer is released, then it ends once and stops following', () => {
    // Given a drag in progress
    const onMove = vi.fn()
    const onEnd = vi.fn()
    followPointer(onMove, onEnd)

    // When the pointer is released, then moves on
    window.dispatchEvent(new MouseEvent('pointerup'))
    move()
    window.dispatchEvent(new MouseEvent('pointerup'))

    // Then the drag ended once and later moves are ignored
    expect(onEnd).toHaveBeenCalledTimes(1)
    expect(onMove).not.toHaveBeenCalled()
  })

  it('given a drag, when the browser cancels it, then it ends as on release', () => {
    // Given a drag in progress, as a touch the browser may take over
    const onMove = vi.fn()
    const onEnd = vi.fn()
    followPointer(onMove, onEnd)

    // When the drag is cancelled
    window.dispatchEvent(new MouseEvent('pointercancel'))
    move()

    // Then it ends, since no pointerup will follow
    expect(onEnd).toHaveBeenCalledTimes(1)
    expect(onMove).not.toHaveBeenCalled()
  })
})
