/**
 * The book rendered with pdf.js: per page a canvas, a selectable text layer,
 * and highlight boxes.  Boxes are in PDF points, origin top-left, so they
 * only need scaling.
 *
 * Text layer CSS lives in `index.css`: importing `pdf_viewer.css` adds the
 * whole viewer's styles, including `.sidebar`, `.error` and `--bg`, to the
 * app.  Primary-button drag selects text; Space+drag or middle-drag pans.
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { Box, SourceExcerpt } from '../../api'
import { followPointer } from '../../shared/pointer'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

/** One document per session; pdf.js fetches it by byte range. */
let document_: Promise<pdfjs.PDFDocumentProxy> | null = null
const load = () =>
  (document_ ??= pdfjs.getDocument({ url: '/api/pdf' }).promise)

type Points = { width: number; height: number }

/**
 * The page count and page 1's size in points.  Every SRD page is the same
 * size, so this sizes pages and places their boxes before they render.
 */
function useShape() {
  const [shape, setShape] = useState<{ count: number; points: Points } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const pdf = await load()
        const viewport = (await pdf.getPage(1)).getViewport({ scale: 1 })
        if (!cancelled) {
          setShape({ count: pdf.numPages,
                     points: { width: viewport.width, height: viewport.height } })
        }
      } catch (failure) {
        if (!cancelled) setError(String(failure))
      }
    })()
    return () => { cancelled = true }
  }, [])

  return { shape, error }
}

// Shared by every page without boxes, so their box effects never refire.
const NO_BOXES: Box[] = []

type Props = {
  zoom: number
  /** The open section: its lines are boxed and its first line scrolled to. */
  excerpt: SourceExcerpt | null
  /** Changes on every citation, so citing the open section again scrolls. */
  visit: number
  /** `nth` changes per request, so the same page twice still scrolls. */
  jumpTo: { page: number; nth: number } | null
}

/**
 * Every page, rendered lazily near the viewport.  Pages stay mounted when
 * the open section changes; only their boxes do.  The page holding the
 * section's first line renders at once and scrolls to it.
 */
export function PdfBook({ zoom, excerpt, visit, jumpTo }: Props) {
  const { shape: book, error: shapeError } = useShape()
  const [pageError, setError] = useState<string | null>(null)
  const error = shapeError ?? pageError
  // Once here rather than in each of the 364 pages.
  const armed = useSpaceHeld()
  const root = useRef<HTMLDivElement>(null)

  const boxesByPage = useMemo(() => {
    const byPage = new Map<number, Box[]>()
    for (const box of excerpt?.boxes ?? []) {
      byPage.set(box.page, [...(byPage.get(box.page) ?? []), box])
    }
    return byPage
  }, [excerpt])
  // Only one page may scroll itself into view: otherwise whichever renders
  // last wins and the panel opens partway through the section.
  const cited = excerpt ? (excerpt.boxes[0]?.page ?? excerpt.page) : null

  // Also on `book`, so a jump requested before the list existed still lands.
  useEffect(() => {
    if (!jumpTo) return
    root.current?.querySelector(`[data-page="${jumpTo.page}"]`)
      ?.scrollIntoView({ block: 'start' })
  }, [jumpTo, book])

  if (error) return <p className="error">{error}</p>
  if (!book) return <p className="muted">Loading the book…</p>

  return (
    <div className={armed ? 'pdf grabbable' : 'pdf'} ref={root}>
      {Array.from({ length: book.count }, (_, index) => {
        const page = index + 1
        const isCited = page === cited
        return (
          <Page key={page} page={page} zoom={zoom} points={book.points}
                boxes={boxesByPage.get(page) ?? NO_BOXES}
                eager={isCited} armed={armed} onError={setError}
                scrollKey={isCited ? `${visit}:${excerpt!.section_id}` : undefined} />
        )
      })}
    </div>
  )
}

function Page({ page, zoom, boxes, points, eager, armed, scrollKey, onError }: {
  page: number
  zoom: number
  boxes: Box[]
  /** The page's size in points. */
  points: Points
  /** Render without waiting to scroll near. */
  eager?: boolean
  /** Space is held: primary drag pans. */
  armed?: boolean
  /** Scroll to the first box (or the page top) whenever this changes. */
  scrollKey?: string
  onError: (message: string) => void
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const text = useRef<HTMLDivElement>(null)
  const [near, setNear] = useState(!!eager)
  // Horizontal scroll is on the figure, vertical on the panel body;
  // `scrollIntoView` only handles the latter (see the scrollLeft effect).
  const frame = useRef<HTMLElement>(null)
  const scrolledFor = useRef<string | undefined>(undefined)

  const onPointerDown = usePan(frame, armed)
  useSelecting(text)

  // Display size tracks the live width; the bitmap re-renders only once the
  // width has settled, and is stretched until then.
  const width = useWidth(frame)
  const settled = useSettled(width, SETTLE_MS)
  const scale = width ? (width / points.width) * zoom : 0
  // Floored from `width`, not `points * scale`: at Fit, one fractional pixel
  // over adds a scrollbar, and the float product can lose a whole pixel.
  const size = {
    width: Math.floor(width * zoom),
    height: Math.floor(width * zoom * (points.height / points.width)),
  }

  useEffect(() => {
    const box = boxes[0]
    if (!box || !frame.current || !scale) return
    const middle = ((box.x0 + box.x1) / 2) * scale
    frame.current.scrollLeft = Math.max(
      0, middle - frame.current.clientWidth / 2)
  }, [boxes, scale])

  // Once per key: a resize or zoom changes the scale but must not pull the
  // reader back to the citation.
  useEffect(() => {
    if (!scrollKey || scrollKey === scrolledFor.current || !scale) return
    scrolledFor.current = scrollKey
    const first = frame.current?.querySelector('.pdf-boxes span')
    if (first) first.scrollIntoView({ block: 'center' })
    else frame.current?.scrollIntoView({ block: 'start' })
  }, [scrollKey, scale, boxes])

  useEffect(() => {
    if (near || !frame.current) return
    // A page cited after it mounted becomes eager without being near.
    if (eager) { setNear(true); return }
    const watch = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setNear(true)
        watch.disconnect()
      }
    }, { rootMargin: '900px 0px' })
    watch.observe(frame.current)
    return () => watch.disconnect()
  }, [eager, near])

  useEffect(() => {
    if (!near || !settled) return
    let cancelled = false
    // Checked after every await: the canvas may since show another page.
    let task: pdfjs.RenderTask | null = null

    ;(async () => {
      try {
        const pdf = await load()
        const rendered = await pdf.getPage(page)
        if (cancelled || !canvas.current) return

        const unscaled = rendered.getViewport({ scale: 1 })
        // Measured on the figure: .pdf-stack takes its width from the canvas.
        const viewport = rendered.getViewport({
          scale: (settled / unscaled.width) * zoom,
        })

        // Rendered off screen, then copied: resizing the visible canvas
        // clears it.  Sized in device pixels for high-DPI screens.
        const ratio = window.devicePixelRatio || 1
        const offscreen = document.createElement('canvas')
        offscreen.width = Math.floor(viewport.width * ratio)
        offscreen.height = Math.floor(viewport.height * ratio)
        task = rendered.render({
          canvas: offscreen,
          canvasContext: offscreen.getContext('2d')!,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        })
        await task.promise
        if (cancelled || !canvas.current || !text.current) return
        canvas.current.width = offscreen.width
        canvas.current.height = offscreen.height
        canvas.current.getContext('2d')!.drawImage(offscreen, 0, 0)

        // Spans are positioned in percentages and sized by
        // `--total-scale-factor`, so the layer follows resizes unrebuilt.
        text.current.replaceChildren()
        await new pdfjs.TextLayer({
          textContentSource: await rendered.getTextContent(),
          container: text.current,
          viewport,
        }).render()

        // Must be the last child; `replaceChildren` removed it.
        if (!cancelled) text.current.append(endOfContent())
      } catch (failure) {
        if (!cancelled && (failure as Error).name !== 'RenderingCancelledException') {
          onError(String(failure))
        }
      }
    })()

    return () => {
      cancelled = true
      task?.cancel()
    }
  }, [page, zoom, near, settled, onError])

  return (
    <figure className="pdf-page" ref={frame} data-page={page}
            onPointerDown={onPointerDown}
            // Suppress middle-click autoscroll, which fights the pan.
            onAuxClick={(event) => event.preventDefault()}>
      <div className="pdf-stack" style={{ height: size.height || undefined }}>
        <canvas ref={canvas}
                style={{ width: size.width || '100%', height: size.height || 'auto' }} />
        {/* Must be --total-scale-factor; with --scale-factor spans get
            font-size 0. */}
        <div ref={text} className="textLayer"
             style={{ '--total-scale-factor': scale } as React.CSSProperties} />
        <div className="pdf-boxes">
          {boxes.map((box, index) => (
            <span key={index}
                  style={{
                    left: box.x0 * scale,
                    top: box.y0 * scale,
                    width: (box.x1 - box.x0) * scale,
                    height: (box.y1 - box.y0) * scale,
                  }} />
          ))}
        </div>
      </div>
      <figcaption>p. {page}</figcaption>
    </figure>
  )
}

/* ── fitting ───────────────────────────────────────────────────────── */

const SETTLE_MS = 150

/**
 * An element's `clientWidth`, kept current.  Not the observer entry's size,
 * which excludes the element's scrollbar differently from the render.
 */
function useWidth(ref: React.RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState(0)

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => setWidth(element.clientWidth)
    measure()
    const watch = new ResizeObserver(measure)
    watch.observe(element)
    return () => watch.disconnect()
  }, [ref])

  return width
}

/** `value` once unchanged for `ms`; the first non-zero value is immediate. */
export function useSettled(value: number, ms: number) {
  const [settled, setSettled] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), settled ? ms : 0)
    return () => clearTimeout(timer)
  }, [value, ms, settled])

  return settled
}

/* ── panning ───────────────────────────────────────────────────────── */

// Elements where Space has its own meaning.
const TYPING = 'input, textarea, select, button, a[href], [contenteditable]'

/**
 * Whether Space is held outside `TYPING` elements.  Its default (scrolling)
 * is prevented.  `blur` also releases it, since the `keyup` never arrives
 * if the window loses focus.
 */
function useSpaceHeld() {
  const [held, setHeld] = useState(false)

  useEffect(() => {
    const typing = (event: KeyboardEvent) =>
      event.target instanceof Element && event.target.closest(TYPING)

    const down = (event: KeyboardEvent) => {
      if (event.code !== 'Space' || typing(event)) return
      event.preventDefault()
      setHeld(true)
    }
    const up = (event: KeyboardEvent) => {
      if (event.code === 'Space') setHeld(false)
    }
    const release = () => setHeld(false)

    window.addEventListener('keydown', down)
    window.addEventListener('keyup', up)
    window.addEventListener('blur', release)
    return () => {
      window.removeEventListener('keydown', down)
      window.removeEventListener('keyup', up)
      window.removeEventListener('blur', release)
    }
  }, [])

  return held
}

/** The nearest ancestor that scrolls vertically and overflows. */
export function verticalScroller(from: Element | null): HTMLElement | null {
  for (let node = from?.parentElement; node; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflowY
    if ((overflow === 'auto' || overflow === 'scroll') &&
        node.scrollHeight > node.clientHeight) return node
  }
  return null
}

/** Pan by scrolling the figure horizontally and its scroller vertically. */
function usePan(frame: React.RefObject<HTMLElement | null>, armed?: boolean) {
  return useCallback((event: React.PointerEvent) => {
    const page = frame.current
    // Middle button, or primary with Space held; plain primary selects.
    if (!page || (event.button !== 1 && !(armed && event.button === 0))) return
    event.preventDefault()

    const pane = verticalScroller(page)
    const startX = event.clientX
    const startY = event.clientY
    const from = { left: page.scrollLeft, top: pane?.scrollTop ?? 0 }

    document.body.classList.add('panning')
    followPointer((moved) => {
      page.scrollLeft = from.left - (moved.clientX - startX)
      if (pane) pane.scrollTop = from.top - (moved.clientY - startY)
    }, () => document.body.classList.remove('panning'))
  }, [frame, armed])
}

/* ── selecting ─────────────────────────────────────────────────────── */

/**
 * pdf.js's `.endOfContent` block, copied from `TextLayerBuilder`.  Covering
 * the layer during a drag, it stops a pointer over a gap from extending the
 * selection to the nearest text in DOM order (often the other column).
 */
const endOfContent = () => {
  const element = document.createElement('div')
  element.className = 'endOfContent'
  return element
}

/**
 * Toggle `.selecting` on the layer while the pointer is down.  pdf.js's
 * repositioning of the block on `selectionchange` is omitted; it skips that
 * itself on Firefox and Chromium 148+.
 */
function useSelecting(layer: React.RefObject<HTMLElement | null>) {
  useEffect(() => {
    const element = layer.current
    if (!element) return

    const start = () => element.classList.add('selecting')
    const stop = () => element.classList.remove('selecting')

    element.addEventListener('pointerdown', start)
    window.addEventListener('pointerup', stop)
    window.addEventListener('blur', stop)
    return () => {
      element.removeEventListener('pointerdown', start)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('blur', stop)
    }
  }, [layer])
}
