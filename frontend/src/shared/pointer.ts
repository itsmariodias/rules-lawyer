/** Drags that outlive the element they started on. */

/**
 * Call `onMove` with every pointer move until the pointer is released or the
 * drag is cancelled, then `onEnd` once.  On the window, since the pointer
 * leaves a small handle or node mid-drag; `pointercancel` ends it too,
 * because a touch the browser takes over for scrolling never sends
 * `pointerup`.
 */
export function followPointer(onMove: (event: PointerEvent) => void,
                              onEnd?: () => void): void {
  const end = () => {
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', end)
    window.removeEventListener('pointercancel', end)
    onEnd?.()
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', end)
  window.addEventListener('pointercancel', end)
}
