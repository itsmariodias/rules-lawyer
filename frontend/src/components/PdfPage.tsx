/**
 * A citation, drawn on the page it was printed on.
 *
 * The rectangles come from `layout.py`, which computed them while turning
 * the PDF into markdown and now keeps them instead of discarding them. They
 * are in PDF points with the origin top-left — the same space PDF.js's
 * viewport uses — so `viewport.scale` is the only conversion needed.
 *
 * A text layer is rendered over the canvas so the facsimile stays
 * selectable and copyable, which is the one thing a bitmap of a page would
 * otherwise cost. Its styles are ours (see `index.css`) rather than
 * `pdfjs-dist/web/pdf_viewer.css`: that file is the whole viewer chrome,
 * and importing it put a `.sidebar`, a `.resizer`, an `.error` and 376
 * `:root` variables — including `--bg` — into this app's cascade.
 *
 * That text layer is also why panning is a second gesture rather than the
 * obvious one. Above Fit the page is larger than the panel in both axes and
 * the only way to move it was a scrollbar per axis, but the primary button
 * already means *select* here, and taking that back would cost the one
 * thing the layer exists for. So the hand is armed by holding Space or by
 * using the middle button, and the drag scrolls rather than transforms:
 * zoom is rasterised into the viewport, so both axes are already real
 * overflow boxes and the canvas, the text and the boxes stay registered
 * with no coordinate space of our own.
 */

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import type { SourceExcerpt } from '../api'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

/**
 * One document for the session.
 *
 * `getDocument` issues byte-range requests, so this fetches the few pages
 * actually rendered rather than all 5.8 MB, and every later citation reuses
 * the same handle and its page cache.
 */
let document_: Promise<pdfjs.PDFDocumentProxy> | null = null
const load = () =>
  (document_ ??= pdfjs.getDocument({ url: '/api/pdf' }).promise)

type Props = { excerpt: SourceExcerpt; zoom: number }

export function PdfPage({ excerpt, zoom }: Props) {
  const [error, setError] = useState<string | null>(null)
  const armed = useSpaceHeld()
  const pages = excerpt.pages?.length ? excerpt.pages : [excerpt.page ?? 1]

  return (
    <div className={armed ? 'pdf grabbable' : 'pdf'}>
      {error && <p className="error">{error}</p>}
      {pages.map((page) => (
        <Page key={page} page={page} zoom={zoom} onError={setError} eager
              armed={armed}
              boxes={excerpt.boxes.filter((b) => b.page === page)} />
      ))}
    </div>
  )
}

/**
 * The whole book, when nothing is cited.
 *
 * The panel is a reader before it is a citation viewer, so with no passage
 * open it shows the SRD from the first page. All 364 are listed but only
 * the ones near the viewport are rendered — `getDocument` fetches by byte
 * range, so scrolling costs the pages you actually reach. Every page is the
 * same size in this book, so page 1's aspect ratio sizes the placeholders
 * and the scrollbar tells the truth before anything has been drawn.
 */
export function PdfBook({ zoom, jumpTo }: {
  zoom: number
  /** A page to scroll to, and how many times one has been asked for: the
      same page twice in a row is still a request to go back to it. */
  jumpTo: { page: number; nth: number } | null
}) {
  const [book, setBook] = useState<{ count: number; aspect: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Once for the book, not once per page: this mode mounts 364 of those.
  const armed = useSpaceHeld()
  const root = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const pdf = await load()
        const viewport = (await pdf.getPage(1)).getViewport({ scale: 1 })
        if (!cancelled) {
          setBook({ count: pdf.numPages, aspect: viewport.height / viewport.width })
        }
      } catch (failure) {
        if (!cancelled) setError(String(failure))
      }
    })()
    return () => { cancelled = true }
  }, [])

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
      {Array.from({ length: book.count }, (_, index) => (
        <Page key={index + 1} page={index + 1} zoom={zoom} boxes={[]}
              aspect={book.aspect} armed={armed} onError={setError} />
      ))}
    </div>
  )
}

function Page({ page, zoom, boxes, aspect, eager, armed, onError }: {
  page: number
  zoom: number
  boxes: SourceExcerpt['boxes']
  /** height/width of a page, for the placeholder an unrendered page leaves. */
  aspect?: number
  /** Render immediately, for the one or two pages a citation falls on. */
  eager?: boolean
  /** Space is down, so a primary drag pans instead of selecting. */
  armed?: boolean
  onError: (message: string) => void
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const text = useRef<HTMLDivElement>(null)
  /** The page's own size in PDF points, once it has been loaded. */
  const [points, setPoints] = useState<{ width: number; height: number } | null>(null)
  const [near, setNear] = useState(!!eager)

  // Two axes, two scroll containers: the page scrolls horizontally inside
  // its own figure, and vertically inside the panel body. `scrollIntoView`
  // only ever resolved the second, which left every right-column citation
  // clipped at the panel's edge.
  const frame = useRef<HTMLElement>(null)
  const scrollTo = useCallback((element: HTMLSpanElement | null) => {
    element?.scrollIntoView({ block: 'center' })
  }, [])

  const onPointerDown = usePan(frame, armed)
  useSelecting(text)

  // The page follows the panel's width, so dragging the panel wider fills
  // it rather than leaving the page where it was. What is shown is derived
  // from the live width on every frame: the canvas, the text layer and the
  // boxes all scale with it at once. Only the bitmap waits for the width to
  // settle, since redrawing a page per pointer move is a render per pixel;
  // until then the last one is stretched, and sharpens when the drag stops.
  const width = useWidth(frame)
  const settled = useSettled(width, SETTLE_MS)
  const scale = points && width ? (width / points.width) * zoom : 0
  // Floored, not rounded: at Fit the page is the container's own width and
  // a fractional pixel over it is a horizontal scrollbar across the panel.
  // Before the page is loaded its space is still reserved, from the aspect
  // the book passes, so 364 placeholders scroll like 364 pages rather than
  // collapsing to nothing.
  // Width is floored from the width it fits rather than from points times
  // scale, whose float product lands a hair under and loses a whole pixel.
  const size = points && scale
    ? { width: Math.floor(width * zoom),
        height: Math.floor(width * zoom * (points.height / points.width)) }
    : aspect && width
      ? { width: Math.floor(width * zoom),
          height: Math.floor(width * zoom * aspect) }
      : { width: 0, height: 0 }

  useEffect(() => {
    const box = boxes[0]
    if (!box || !frame.current || !scale) return
    const middle = ((box.x0 + box.x1) / 2) * scale
    frame.current.scrollLeft = Math.max(
      0, middle - frame.current.clientWidth / 2)
  }, [boxes, scale])

  // A page is rendered once it is within a screenful of the viewport: far
  // enough ahead that scrolling meets drawn pages, near enough that opening
  // the book does not fetch it all.
  useEffect(() => {
    if (eager || near || !frame.current) return
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
    // Rendering into a canvas that React has since reused would paint the
    // wrong page, so every await checks whether this effect is still current.
    let task: pdfjs.RenderTask | null = null

    ;(async () => {
      try {
        const pdf = await load()
        const rendered = await pdf.getPage(page)
        if (cancelled || !canvas.current) return

        const unscaled = rendered.getViewport({ scale: 1 })
        setPoints((current) =>
          current?.width === unscaled.width && current.height === unscaled.height
            ? current : { width: unscaled.width, height: unscaled.height })
        // `settled` is measured on the scrolling figure, never on
        // .pdf-stack: the stack takes its width *from* the canvas, so asking
        // it how wide the canvas should be is circular.
        const viewport = rendered.getViewport({
          scale: (settled / unscaled.width) * zoom,
        })

        // Drawn off screen and copied across once it is finished: resizing
        // a canvas clears it, so drawing into the one on screen would blank
        // the page every time the panel was dragged. The canvas is sized in
        // device pixels and displayed in CSS pixels, so the page stays
        // sharp on a retina display.
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

        // The spans are placed in percentages of the page and sized by
        // `--total-scale-factor`, which is set from the live scale below, so
        // the layer follows a drag without being rebuilt and is rebuilt here
        // only to match the new bitmap.
        text.current.replaceChildren()
        await new pdfjs.TextLayer({
          textContentSource: await rendered.getTextContent(),
          container: text.current,
          viewport,
        }).render()

        // Last among the layer's children, and re-added after every render
        // because `replaceChildren` above clears them. See `useSelecting`.
        if (!cancelled) text.current.append(endOfContent())
      } catch (failure) {
        // A cancelled render is the expected way to interrupt one.
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
            // Middle-click opens the browser's own autoscroll where there is
            // one, which would fight the drag that has already started.
            onAuxClick={(event) => event.preventDefault()}>
      <div className="pdf-stack" style={{ height: size.height || undefined }}>
        <canvas ref={canvas}
                style={{ width: size.width || '100%', height: size.height || 'auto' }} />
        {/* `--total-scale-factor`, not `--scale-factor`: it is the name the
            text layer's own rules read, and without it every span renders
            at font-size 0 and selection lands nowhere near the glyphs. */}
        <div ref={text} className="textLayer"
             style={{ '--total-scale-factor': scale } as React.CSSProperties} />
        <div className="pdf-boxes">
          {boxes.map((box, index) => (
            <span key={index}
                  // The first rectangle is what the panel scrolls to: at a
                  // readable zoom the page is taller than the panel, and a
                  // citation that opens at the top of page 186 has not
                  // actually shown you anything.
                  ref={index === 0 ? scrollTo : undefined}
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

/** How long the width must hold still before the page is redrawn for it. */
const SETTLE_MS = 150

/**
 * The element's width, kept current as it changes.
 *
 * Read off `clientWidth` rather than the observer's entry, which measures
 * the content box and so would disagree with the render about the
 * figure's own scrollbar.
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

/**
 * `value`, once it has stopped changing for `ms`.
 *
 * The first value is taken at once: a page opening should draw straight
 * away rather than wait out a drag that never happened.
 */
export function useSettled(value: number, ms: number) {
  const [settled, setSettled] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), settled ? ms : 0)
    return () => clearTimeout(timer)
  }, [value, ms, settled])

  return settled
}

/* ── panning ───────────────────────────────────────────────────────── */

/** What Space must not mean: a character, or pressing the thing in focus. */
const TYPING = 'input, textarea, select, button, a[href], [contenteditable]'

/**
 * Whether Space is being held, which is what arms the hand.
 *
 * The guard is the composer: a space typed into it is a space, and Space on
 * a focused button is still that button. Everywhere else it is prevented,
 * or the same key would also scroll the pane under the reader's hands.
 * `blur` releases it too — a window that loses focus mid-hold never
 * delivers the `keyup`, and the cursor would stay a hand for ever.
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

/**
 * The ancestor a page scrolls vertically inside.
 *
 * Found rather than named: it is `.panel-body` today, but that class is the
 * panel's and this module renders pages, not panels. Pure, so the walk is
 * tested on plain elements.
 */
export function verticalScroller(from: Element | null): HTMLElement | null {
  for (let node = from?.parentElement; node; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflowY
    if ((overflow === 'auto' || overflow === 'scroll') &&
        node.scrollHeight > node.clientHeight) return node
  }
  return null
}

/**
 * Drag the page under the pointer.
 *
 * Two axes, two scroll containers — the figure sideways and the pane above
 * it downwards — so one gesture writes to both. Assigning `scrollLeft` and
 * `scrollTop` clamps itself at either end, which is why there is no bound
 * here to compute.
 *
 * The listeners go on the window rather than the figure, like the panel's
 * own resizer: a pointer routinely leaves the page mid-drag, and the drag
 * must not stop when it does.
 */
function usePan(frame: React.RefObject<HTMLElement | null>, armed?: boolean) {
  return useCallback((event: React.PointerEvent) => {
    const page = frame.current
    // The middle button, or Space held: the primary button on its own still
    // means select, which is what the text layer is rendered for.
    if (!page || (event.button !== 1 && !(armed && event.button === 0))) return
    event.preventDefault()

    const pane = verticalScroller(page)
    const startX = event.clientX
    const startY = event.clientY
    const from = { left: page.scrollLeft, top: pane?.scrollTop ?? 0 }

    const move = (moved: PointerEvent) => {
      page.scrollLeft = from.left - (moved.clientX - startX)
      if (pane) pane.scrollTop = from.top - (moved.clientY - startY)
    }
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      document.body.classList.remove('panning')
    }

    document.body.classList.add('panning')
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
  }, [frame, armed])
}

/* ── selecting ─────────────────────────────────────────────────────── */

/**
 * The block that keeps a selection inside the lines it was dragged across.
 *
 * Most of a page is gap — between the lines, down the gutter, out in the
 * margins — and a pointer in one is over no span at all, so the browser
 * extends the selection to the nearest text in *DOM order*, which on a
 * two-column page is somewhere else entirely. That is what makes a small
 * drag select half a page. This element covers the layer while a drag is
 * running and sits last among its children, so a pointer in a gap lands on
 * it rather than reaching past it; `user-select: none` keeps it out of
 * whatever is copied.
 *
 * It is pdf.js's own answer to this, and it lives in `TextLayerBuilder` —
 * viewer chrome we do not use — so, like that class's CSS, it is carried
 * here rather than imported.
 */
const endOfContent = () => {
  const element = document.createElement('div')
  element.className = 'endOfContent'
  return element
}

/**
 * When that block is covering the layer: for the length of a drag.
 *
 * pdf.js also *moves* the block around the selection's own anchor, which is
 * what the viewer's `selectionchange` listener is for — and which it skips
 * outright on Firefox and on Chromium 148 and above, where the browser gets
 * this right unaided. So what is carried here is the half that still earns
 * its keep on a current browser: the class, for as long as the pointer is
 * down. `blur` releases it for the same reason the pan does — a window that
 * loses focus mid-drag never sends the `pointerup`.
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
