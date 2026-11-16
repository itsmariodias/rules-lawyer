/** The drag handle between the conversation and the side panel. */

import { useCallback } from 'react'
import { followPointer } from '../shared/pointer'

/** Thread list width; fixed. */
export const SIDEBAR = 260
export const MIN_PANEL = 380
const MIN_CHAT = 420
const STEP = 30

/** Clamp the panel width so the conversation keeps `MIN_CHAT` beside `sidebar`. */
export function clampWidth(width: number, sidebar: number): number {
  const max = window.innerWidth - sidebar - MIN_CHAT
  // On a narrow window `max` < MIN_PANEL; the minimum wins and CSS takes over.
  return Math.max(MIN_PANEL, Math.min(width, max))
}

/** Initial panel width: half the window, within 560..1000 and clamped. */
export const defaultPanel = () =>
  clampWidth(Math.min(1000, Math.max(560, Math.round(window.innerWidth / 2))),
             SIDEBAR)

type Props = {
  width: number
  /** Thread list width; 0 when hidden. */
  sidebar: number
  onResize: (width: number) => void
}

export function Resizer({ width, sidebar, onResize }: Props) {
  const start = useCallback((event: React.PointerEvent) => {
    event.preventDefault()
    document.body.classList.add('resizing')
    followPointer(
      (moved) => onResize(clampWidth(window.innerWidth - moved.clientX, sidebar)),
      () => document.body.classList.remove('resizing'))
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
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') onResize(clampWidth(width + STEP, sidebar))
        else if (event.key === 'ArrowRight') onResize(clampWidth(width - STEP, sidebar))
        else return
        event.preventDefault()
      }}
    >
      {/* 4px grip inside a 13px hit target. */}
      <span className="grip" aria-hidden="true" />
    </div>
  )
}
