/**
 * A citation, drawn on the page it was printed on.
 *
 * pdf.js itself is mocked — what is worth testing here is ours: that the
 * rectangles `layout.py` computed are scaled by the viewport and drawn over
 * the right page, that the text layer is told the variable name its own
 * rules actually read, and that the book reserves the space of pages it has
 * not drawn yet.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SourceExcerpt } from '../api'
import { PdfBook, PdfPage } from './PdfPage'

const textLayer = vi.fn()

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker' }))
vi.mock('pdfjs-dist', () => {
  const viewport = (scale: number) => ({ scale, width: 612 * scale,
                                         height: 792 * scale })
  const page = {
    getViewport: ({ scale }: { scale: number }) => viewport(scale),
    render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }),
    getTextContent: () => Promise.resolve({ items: [] }),
  }
  return {
    GlobalWorkerOptions: { workerSrc: '' },
    getDocument: () => ({ promise: Promise.resolve({
      numPages: 364, getPage: () => Promise.resolve(page) }) }),
    TextLayer: class {
      constructor(options: unknown) { textLayer(options) }
      render() { return Promise.resolve() }
    },
  }
})

const excerpt = (overrides: Partial<SourceExcerpt> = {}): SourceExcerpt => ({
  section_id: '11.2.114', heading: 'Prone [Condition]',
  entity_type: 'glossary_term', page: 186, text: 'While you have…',
  highlight: null, pages: [186],
  boxes: [{ page: 186, x0: 57, y0: 100, x1: 300, y1: 112 }],
  parent: null, children: [], ...overrides,
})

beforeEach(() => {
  // jsdom's canvas has no 2D context, and the render call needs one.
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never
  Element.prototype.scrollIntoView = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'clientWidth',
                        { value: 612, configurable: true })
})

describe('PdfPage', () => {
  it('given a citation, when drawn, then the page it was printed on is shown', async () => {
    // Given a citation on page 186
    render(<PdfPage excerpt={excerpt()} zoom={1} />)

    // When it is drawn
    // Then the page is captioned by its own number
    expect(await screen.findByText('p. 186')).toBeInTheDocument()
  })

  it('given a citation across two pages, when drawn, then both are shown', async () => {
    /** A passage that runs over a page break is cited on both. */
    // Given a citation whose lines fall on two pages
    render(<PdfPage excerpt={excerpt({ pages: [186, 187] })} zoom={1} />)

    // When it is drawn
    // Then neither half is dropped
    expect(await screen.findByText('p. 186')).toBeInTheDocument()
    expect(screen.getByText('p. 187')).toBeInTheDocument()
  })

  it('given no page list, when drawn, then the section’s own page is used', async () => {
    /** An artifact from before the anchors existed carries no boxes. */
    // Given an excerpt with geometry but no page list
    render(<PdfPage excerpt={excerpt({ pages: [], boxes: [] })} zoom={1} />)

    // When it is drawn
    // Then the citation still opens on its page
    expect(await screen.findByText('p. 186')).toBeInTheDocument()
  })

  it('given rectangles, when drawn, then they are scaled by the viewport', async () => {
    /**
     * The boxes are in PDF points with the origin top-left — the same space
     * pdf.js's viewport uses — so the scale is the only conversion needed.
     */
    // Given a citation whose lines are boxed
    const { container } = render(<PdfPage excerpt={excerpt()} zoom={2} />)

    // When the page is drawn at 2×
    await screen.findByText('p. 186')

    // Then each box is the rectangle in points, times the scale
    await waitFor(() => {
      const box = container.querySelector('.pdf-boxes span') as HTMLElement
      expect(box.style.left).toBe('114px')
      expect(box.style.width).toBe('486px')
      expect(box.style.height).toBe('24px')
    })
  })

  it('given a rectangle, when drawn, then the panel scrolls to the first one', async () => {
    /**
     * At a readable zoom the page is taller than the panel, and a citation
     * that opens at the top of page 186 has not actually shown you anything.
     */
    // Given a citation partway down a page
    render(<PdfPage excerpt={excerpt()} zoom={1} />)

    // When it is drawn
    await screen.findByText('p. 186')

    // Then the reader is taken to the passage rather than to the page
    await waitFor(() => expect(Element.prototype.scrollIntoView)
      .toHaveBeenCalledWith({ block: 'center' }))
  })

  it('given a rendered page, when the text layer is built, then it gets the right variable', async () => {
    /**
     * `--total-scale-factor`, not `--scale-factor`: it is the name the text
     * layer's own rules read, and without it every span renders at font-size
     * 0 and selection lands nowhere near the glyphs.
     */
    // Given a page rendered at 1×
    const { container } = render(<PdfPage excerpt={excerpt()} zoom={1} />)

    // When the text layer has been built
    await waitFor(() => expect(textLayer).toHaveBeenCalled())

    // Then the scale is published under the name those rules use
    const layer = container.querySelector('.textLayer') as HTMLElement
    expect(layer.style.getPropertyValue('--total-scale-factor')).toBe('1')
  })
})

describe('PdfBook', () => {
  it('given no citation, when opened, then every page of the book is listed', async () => {
    /** The panel is a reader before it is a citation viewer. */
    // Given the book with nothing cited
    render(<PdfBook zoom={1} jumpTo={null} />)

    // When it opens
    // Then the whole book is there to scroll, from page one
    expect(await screen.findByText('p. 1')).toBeInTheDocument()
    expect(screen.getByText('p. 364')).toBeInTheDocument()
  })

  it('given a page number, when asked for, then the book scrolls to it', async () => {
    // Given the book, open
    const { rerender } = render(<PdfBook zoom={1} jumpTo={null} />)
    await screen.findByText('p. 1')

    // When a page is asked for
    rerender(<PdfBook zoom={1} jumpTo={{ page: 186, nth: 1 }} />)

    // Then the reader is taken there
    expect(Element.prototype.scrollIntoView)
      .toHaveBeenCalledWith({ block: 'start' })
  })

  it('given the same page twice, when asked for again, then it still scrolls', async () => {
    /** The same page twice in a row is still a request to go back to it. */
    // Given the book already scrolled to a page
    const { rerender } = render(
      <PdfBook zoom={1} jumpTo={{ page: 186, nth: 1 }} />)
    await screen.findByText('p. 1')
    vi.mocked(Element.prototype.scrollIntoView).mockClear()

    // When the same page is asked for again, under a new count
    rerender(<PdfBook zoom={1} jumpTo={{ page: 186, nth: 2 }} />)

    // Then the request is not swallowed as a no-op
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })
})
