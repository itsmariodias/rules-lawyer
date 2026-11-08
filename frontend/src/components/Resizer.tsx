/**
 * The drag handle between the conversation and the page panel.
 *
 * How wide the page facsimile needs to be is a question about the reader's
 * screen and eyes, not one this application can answer, so it is a control
 * rather than a constant. The thread list is not: a conversation title is
 * one line of text, and a width that suits it is a fact about the text.
 */

import { useCallback } from 'react'

/** The thread list: wide enough for a title, and fixed. */
export const SIDEBAR = 260
/** Enough panel to read a column of the SRD. */
export const MIN_PANEL = 380
/** Leave the conversation readable however the panel is dragged. */
const MIN_CHAT = 420
const STEP = 30

/**
 * Clamp the panel, given how much the thread list is already taking.
 *
 * The two share a window, so the panel cannot be clamped alone: widening it
 * to the window's edge while the thread list is open would leave nothing in
 * between.
 */
export function clampWidth(width: number, sidebar: number): number {
  const max = window.innerWidth - sidebar - MIN_CHAT
  // `max` can fall below the minimum on a very narrow window; the minimum
  // wins, and the layout's own media query takes over from there.
  return Math.max(MIN_PANEL, Math.min(width, max))
}

/**
 * How wide the panel starts, on a screen we have not seen before.
 *
 * Proportional rather than fixed: the page is rendered to fit the panel, so
 * the panel's width *is* the reading size. Half the window gives a legible
 * page on a large display and still leaves the conversation usable on a
 * laptop.
 */
export const defaultPanel = () =>
  clampWidth(Math.min(1000, Math.max(560, Math.round(window.innerWidth / 2))),
             SIDEBAR)

type Props = {
  width: number
  /** How much of the window the thread list is taking: none when hidden. */
  sidebar: number
  onResize: (width: number) => void
}

export function Resizer({ width, sidebar, onResize }: Props) {
  const start = useCallback((event: React.PointerEvent) => {
    event.preventDefault()
    // Listeners go on the window, not the handle: the pointer routinely
    // leaves a 13px target mid-drag, and the drag must not stop when it does.
    // The panel grows leftwards from the right-hand edge.
    const move = (moved: PointerEvent) =>
      onResize(clampWidth(window.innerWidth - moved.clientX, sidebar))
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      document.body.classList.remove('resizing')
    }
    document.body.classList.add('resizing')
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }, [sidebar, onResize])

  return (
    <div
      className="resizer"
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the page panel"
      aria-valuenow={Math.round(width)}
      tabIndex={0}
      onPointerDown={start}
      // Dragging is not the only way to move a divider.
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') onResize(clampWidth(width + STEP, sidebar))
        else if (event.key === 'ArrowRight') onResize(clampWidth(width - STEP, sidebar))
        else return
        event.preventDefault()
      }}
    >
      {/* The target is wider than the mark: a 4px bar is easy to see and
          miserable to hit, so the grip is drawn small and grabbed large. */}
      <span className="grip" aria-hidden="true" />
    </div>
  )
}
