/**
 * The drag handles either side of the conversation.
 *
 * How wide the thread list and the page facsimile need to be are questions
 * about the reader's screen and eyes, not ones this application can answer
 * — so both are controls rather than constants. One component serves both
 * edges; only which direction "wider" points differs.
 */

import { useCallback } from 'react'

export const MIN_SIDEBAR = 180
/** A thread title is one line of text; past this it is just whitespace. */
export const MAX_SIDEBAR = 460
/** Enough panel to read a column of the SRD. */
export const MIN_PANEL = 380
/** Leave the conversation readable however the edges are dragged. */
const MIN_CHAT = 420
const STEP = 30

export type Edge = 'sidebar' | 'panel'

/**
 * Clamp one edge, given how much the opposite edge is already taking.
 *
 * The two share a window, so neither can be clamped alone: widening the
 * panel to its own maximum while the sidebar is wide would leave nothing
 * in between.
 */
export function clampWidth(edge: Edge, width: number, other: number): number {
  const min = edge === 'sidebar' ? MIN_SIDEBAR : MIN_PANEL
  const room = window.innerWidth - other - MIN_CHAT
  const max = edge === 'sidebar' ? Math.min(MAX_SIDEBAR, room) : room
  // `max` can fall below `min` on a very narrow window; the minimum wins,
  // and the layout's own media query takes over from there.
  return Math.max(min, Math.min(width, Math.max(min, max)))
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
  clampWidth('panel',
             Math.min(1000, Math.max(560, Math.round(window.innerWidth / 2))),
             MIN_SIDEBAR)

type Props = {
  edge: Edge
  width: number
  other: number
  onResize: (width: number) => void
}

export function Resizer({ edge, width, other, onResize }: Props) {
  // The sidebar grows rightwards from x=0, the panel leftwards from the
  // right-hand edge. That is the only difference between the two.
  const measure = (x: number) =>
    edge === 'sidebar' ? x : window.innerWidth - x

  const start = useCallback((event: React.PointerEvent) => {
    event.preventDefault()
    // Listeners go on the window, not the handle: the pointer routinely
    // leaves a 13px target mid-drag, and the drag must not stop when it does.
    const move = (moved: PointerEvent) =>
      onResize(clampWidth(edge, measure(moved.clientX), other))
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      document.body.classList.remove('resizing')
    }
    document.body.classList.add('resizing')
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
  }, [edge, other, onResize])

  return (
    <div
      className={`resizer resizer-${edge}`}
      role="separator"
      aria-orientation="vertical"
      aria-label={edge === 'sidebar'
        ? 'Resize the conversation list' : 'Resize the page panel'}
      aria-valuenow={Math.round(width)}
      tabIndex={0}
      onPointerDown={start}
      // Dragging is not the only way to move a divider.
      onKeyDown={(event) => {
        const wider = edge === 'sidebar' ? 'ArrowRight' : 'ArrowLeft'
        const narrower = edge === 'sidebar' ? 'ArrowLeft' : 'ArrowRight'
        if (event.key === wider) onResize(clampWidth(edge, width + STEP, other))
        else if (event.key === narrower) onResize(clampWidth(edge, width - STEP, other))
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
