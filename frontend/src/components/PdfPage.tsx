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
  const pages = excerpt.pages?.length ? excerpt.pages : [excerpt.page ?? 1]

  return (
    <div className="pdf">
      {error && <p className="error">{error}</p>}
      {pages.map((page) => (
        <Page key={page} page={page} zoom={zoom} onError={setError} eager
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
    <div className="pdf" ref={root}>
      {Array.from({ length: book.count }, (_, index) => (
        <Page key={index + 1} page={index + 1} zoom={zoom} boxes={[]}
              aspect={book.aspect} onError={setError} />
      ))}
    </div>
  )
}

function Page({ page, zoom, boxes, aspect, eager, onError }: {
  page: number
  zoom: number
  boxes: SourceExcerpt['boxes']
  /** height/width of a page, for the placeholder an unrendered page leaves. */
  aspect?: number
  /** Render immediately, for the one or two pages a citation falls on. */
  eager?: boolean
  onError: (message: string) => void
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const text = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(1)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [near, setNear] = useState(!!eager)

  // Two axes, two scroll containers: the page scrolls horizontally inside
  // its own figure, and vertically inside the panel body. `scrollIntoView`
  // only ever resolved the second, which left every right-column citation
  // clipped at the panel's edge.
  const frame = useRef<HTMLElement>(null)
  const scrollTo = useCallback((element: HTMLSpanElement | null) => {
    element?.scrollIntoView({ block: 'center' })
  }, [])

  useEffect(() => {
    const box = boxes[0]
    if (!box || !frame.current || !scale) return
    const middle = ((box.x0 + box.x1) / 2) * scale
    frame.current.scrollLeft = Math.max(
      0, middle - frame.current.clientWidth / 2)
  }, [boxes, scale])

  // Reserve the page's space before it is drawn, so 364 placeholders scroll
  // like 364 pages rather than collapsing to nothing.
  useLayoutEffect(() => {
    if (!aspect || !frame.current) return
    const width = Math.floor(frame.current.clientWidth * zoom)
    setSize({ width, height: Math.floor(width * aspect) })
  }, [aspect, zoom])

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
    if (!near) return
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
        // Measured on the scrolling figure, never on .pdf-stack: the stack
        // takes its width *from* the canvas, so asking it how wide the
        // canvas should be is circular.
        const width = frame.current!.clientWidth
        const viewport = rendered.getViewport({
          scale: (width / unscaled.width) * zoom,
        })

        // The canvas is sized in device pixels and displayed in CSS pixels,
        // so the page stays sharp on a retina display.
        const ratio = window.devicePixelRatio || 1
        canvas.current.width = Math.floor(viewport.width * ratio)
        canvas.current.height = Math.floor(viewport.height * ratio)
        // Floored, not rounded: at Fit the viewport is the container's own
        // width and a fractional pixel over it is a horizontal scrollbar
        // across the whole panel.
        setSize({
          width: Math.floor(viewport.width),
          height: Math.floor(viewport.height),
        })
        setScale(viewport.scale)

        task = rendered.render({
          canvas: canvas.current,
          canvasContext: canvas.current.getContext('2d')!,
          viewport,
          transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
        })
        await task.promise
        if (cancelled || !text.current) return

        text.current.replaceChildren()
        // `--total-scale-factor`, not `--scale-factor`: it is the name the
        // text layer's own rules read, and without it every span renders at
        // font-size 0 and selection lands nowhere near the glyphs.
        text.current.style.setProperty('--total-scale-factor',
                                       String(viewport.scale))
        await new pdfjs.TextLayer({
          textContentSource: await rendered.getTextContent(),
          container: text.current,
          viewport,
        }).render()
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
  }, [page, zoom, near, onError])

  return (
    <figure className="pdf-page" ref={frame} data-page={page}>
      <div className="pdf-stack" style={{ height: size.height || undefined }}>
        <canvas ref={canvas}
                style={{ width: size.width || '100%', height: size.height || 'auto' }} />
        <div ref={text} className="textLayer" />
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
