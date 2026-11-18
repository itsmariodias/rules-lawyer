/** pdf.js is mocked. */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SourceExcerpt } from '../../api'
import { PdfBook, verticalScroller } from './PdfPage'

const textLayer = vi.fn()
const renders = vi.fn()

vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: 'worker' }))
vi.mock('pdfjs-dist', () => {
  const viewport = (scale: number) => ({ scale, width: 612 * scale,
                                         height: 792 * scale })
  const page = {
    getViewport: ({ scale }: { scale: number }) => viewport(scale),
    render: (options: unknown) => {
      renders(options)
      return { promise: Promise.resolve(), cancel: vi.fn() }
    },
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
  ancestors: [], parent: null, children: [], ...overrides,
})

beforeEach(() => {
  // jsdom's canvas has no 2D context.
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ({ drawImage: vi.fn() })) as never
  renders.mockClear()
  Element.prototype.scrollIntoView = vi.fn()
  Object.defineProperty(HTMLElement.prototype, 'clientWidth',
                        { value: 612, configurable: true })
  // jsdom has no layout: replace its read-only zero scroll metrics with
  // writable per-element values that overflow.
  for (const [name, value] of [['scrollLeft', 0], ['scrollTop', 0],
                               ['clientHeight', 500], ['scrollHeight', 2000]]) {
    Object.defineProperty(HTMLElement.prototype, name,
                          { value, writable: true, configurable: true })
  }
  document.body.className = ''
})

type BookProps = Parameters<typeof PdfBook>[0]

const book = (props: Partial<BookProps> = {}) =>
  <PdfBook zoom={1} excerpt={excerpt()} visit={1} jumpTo={null} {...props} />

/** Render the book inside a scrolling container, as the panel does. */
function inAPane(zoom = 2) {
  const pane = document.createElement('div')
  pane.style.overflowY = 'auto'
  document.body.append(pane)
  const view = render(book({ zoom }), { container: pane })
  return { pane, ...view }
}

const pageOf = (container: HTMLElement, page = 186) =>
  container.querySelector(`[data-page="${page}"]`) as HTMLElement

/** Every ResizeObserver's callback, so a test can resize all the pages. */
function observeResizes() {
  const callbacks: (() => void)[] = []
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { callbacks.push(callback) }
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  return () => act(() => callbacks.forEach((callback) => callback()))
}

describe('PdfBook', () => {
  it('given no citation, when opened, then every page of the book is listed', async () => {
    // Given the book with nothing cited
    const { container } = render(book({ excerpt: null }))

    // When it opens
    // Then the whole book is there to scroll, from page one, with nothing boxed
    expect(await screen.findByText('p. 1')).toBeInTheDocument()
    expect(screen.getByText('p. 364')).toBeInTheDocument()
    expect(container.querySelector('.pdf-boxes span')).toBeNull()
  })

  it('given a citation, when drawn, then its lines are boxed on its page among the rest', async () => {
    // Given a citation on page 186
    const { container } = render(book())

    // When it is drawn
    await screen.findByText('p. 186')

    // Then the whole book is still there, and only that page has a box
    expect(screen.getByText('p. 1')).toBeInTheDocument()
    expect(screen.getByText('p. 364')).toBeInTheDocument()
    expect(container.querySelectorAll('.pdf-boxes span')).toHaveLength(1)
    expect(pageOf(container).querySelector('.pdf-boxes span')).not.toBeNull()
  })

  it('given a citation across two pages, when drawn, then both are boxed', async () => {
    // Given a citation whose lines fall on two pages
    const { container } = render(book({ excerpt: excerpt({
      pages: [186, 187],
      boxes: [{ page: 186, x0: 57, y0: 600, x1: 300, y1: 612 },
              { page: 187, x0: 57, y0: 100, x1: 300, y1: 112 }],
    }) }))

    // When it is drawn
    await screen.findByText('p. 186')

    // Then neither half is dropped
    expect(pageOf(container, 186).querySelector('.pdf-boxes span')).not.toBeNull()
    expect(pageOf(container, 187).querySelector('.pdf-boxes span')).not.toBeNull()
  })

  it('given rectangles, when drawn, then they are scaled by the viewport', async () => {
    // Given a citation whose lines are boxed
    const { container } = render(book({ zoom: 2 }))

    // When the book is drawn at 2×
    await screen.findByText('p. 186')

    // Then each box is the rectangle in points, times the scale
    await waitFor(() => {
      const box = pageOf(container).querySelector('.pdf-boxes span') as HTMLElement
      expect(box.style.left).toBe('114px')
      expect(box.style.width).toBe('486px')
      expect(box.style.height).toBe('24px')
    })
  })

  it('given a rectangle, when drawn, then the book scrolls to it and nowhere else', async () => {
    /** Regression: every page scrolled itself, so the last to render won. */
    // Given a passage boxed on two pages
    const { container } = render(book({ excerpt: excerpt({
      pages: [186, 187],
      boxes: [{ page: 186, x0: 57, y0: 600, x1: 300, y1: 612 },
              { page: 187, x0: 57, y0: 100, x1: 300, y1: 112 }],
    }) }))

    // When it is drawn
    await screen.findByText('p. 187')
    await waitFor(() => expect(Element.prototype.scrollIntoView)
      .toHaveBeenCalledWith({ block: 'center' }))

    // Then the reader is taken to the passage's first line, not to a page
    const scrolled = vi.mocked(Element.prototype.scrollIntoView).mock.contexts
    expect(scrolled).toEqual([pageOf(container, 186).querySelector('.pdf-boxes span')])
  })

  it('given a section with no rectangles, when drawn, then its page is scrolled to', async () => {
    // Given a section with a page but no geometry
    const { container } = render(book({ excerpt: excerpt({ pages: [], boxes: [] }) }))

    // When it is drawn
    await screen.findByText('p. 186')

    // Then the book still opens at it
    await waitFor(() => expect(vi.mocked(Element.prototype.scrollIntoView).mock.contexts)
      .toEqual([pageOf(container)]))
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: 'start' })
  })

  it('given the same citation, when cited again, then it scrolls back to it', async () => {
    // Given a citation already scrolled to
    const { rerender } = render(book())
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled())
    vi.mocked(Element.prototype.scrollIntoView).mockClear()

    // When it is cited again, under a new visit
    rerender(book({ visit: 2 }))

    // Then the reader is taken back to it
    await waitFor(() => expect(Element.prototype.scrollIntoView)
      .toHaveBeenCalledWith({ block: 'center' }))
  })

  it('given a citation scrolled to, when the panel is resized, then the reader is left where they are', async () => {
    // Given a citation already scrolled to
    const resize = observeResizes()
    render(book())
    await waitFor(() => expect(Element.prototype.scrollIntoView).toHaveBeenCalled())
    vi.mocked(Element.prototype.scrollIntoView).mockClear()

    // When the panel is dragged wider
    Object.defineProperty(HTMLElement.prototype, 'clientWidth',
                          { value: 918, configurable: true })
    resize()

    // Then the book is not pulled back to the citation
    expect(Element.prototype.scrollIntoView).not.toHaveBeenCalled()
  })

  it('given a section across many pages, when drawn, then only its first page renders at once', async () => {
    // Given a section boxed across five pages
    const pages = [176, 177, 178, 179, 180]
    render(book({ excerpt: excerpt({
      pages,
      boxes: pages.map((page) => ({ page, x0: 57, y0: 100, x1: 300, y1: 112 })),
    }) }))

    // When it is drawn
    await screen.findByText('p. 180')

    // Then only the first is rendered; the rest wait until they are scrolled near
    await waitFor(() => expect(renders).toHaveBeenCalledTimes(1))
  })

  it('given a new citation, when it opens, then the pages already drawn stay as they are', async () => {
    // Given one citation drawn
    const { container, rerender } = render(book())
    await waitFor(() => expect(renders).toHaveBeenCalledTimes(1))
    const canvas = pageOf(container).querySelector('canvas')

    // When another section, on the next page, is cited
    rerender(book({ visit: 2, excerpt: excerpt({
      section_id: '11.2.115', heading: 'Restrained [Condition]', page: 187,
      pages: [187], boxes: [{ page: 187, x0: 57, y0: 100, x1: 300, y1: 112 }],
    }) }))

    // Then its page is drawn, the first page keeps its canvas unredrawn,
    // and only the old boxes go
    await waitFor(() => expect(renders).toHaveBeenCalledTimes(2))
    expect(pageOf(container).querySelector('canvas')).toBe(canvas)
    expect(pageOf(container).querySelector('.pdf-boxes span')).toBeNull()
    expect(pageOf(container, 187).querySelector('.pdf-boxes span')).not.toBeNull()
  })

  it('given a page further down, when it is scrolled near, then it renders', async () => {
    // Given the book drawn at its citation, another page waiting to be scrolled to
    let reportNear: IntersectionObserverCallback = () => {}
    vi.stubGlobal('IntersectionObserver', class {
      constructor(callback: IntersectionObserverCallback) { reportNear = callback }
      observe() {}
      disconnect() {}
    })
    render(book())
    await waitFor(() => expect(renders).toHaveBeenCalledTimes(1))

    // When that page comes near the viewport
    act(() => reportNear([{ isIntersecting: true } as IntersectionObserverEntry],
                         {} as IntersectionObserver))

    // Then it is drawn too
    await waitFor(() => expect(renders).toHaveBeenCalledTimes(2))
  })

  it('given a page pdf.js cannot draw, when rendered, then the reason is shown', async () => {
    // Given a page whose render fails
    renders.mockImplementationOnce(() => { throw new Error('Invalid page') })

    // When it is drawn
    render(book())

    // Then the reader is told, rather than left with a blank page
    expect(await screen.findByText(/Invalid page/)).toBeInTheDocument()
  })

  it('given a rendered page, when the text layer is built, then it gets the right variable', async () => {
    /** Regression: setting --scale-factor gave every span font-size 0. */
    // Given a page rendered at 1×
    const { container } = render(book())

    // When the text layer has been built
    await waitFor(() => expect(textLayer).toHaveBeenCalled())

    // Then the scale is published under the name those rules use
    const layer = pageOf(container).querySelector('.textLayer') as HTMLElement
    expect(layer.style.getPropertyValue('--total-scale-factor')).toBe('1')
  })

  it('given a drawn page, when the panel is dragged wider, then the page fills it', async () => {
    // Given a page drawn at Fit in a 612px panel
    const resize = observeResizes()
    const { container } = render(book())
    await waitFor(() => expect(renders).toHaveBeenCalledTimes(1))
    const page = pageOf(container)
    const canvas = page.querySelector('canvas') as HTMLCanvasElement
    expect(canvas.style.width).toBe('612px')

    // When the panel is dragged to half as wide again
    Object.defineProperty(HTMLElement.prototype, 'clientWidth',
                          { value: 918, configurable: true })
    resize()

    // Then the page, its text and its boxes fill it at once, before any redraw
    const layer = page.querySelector('.textLayer') as HTMLElement
    const box = page.querySelector('.pdf-boxes span') as HTMLElement
    expect(canvas.style.width).toBe('918px')
    expect(layer.style.getPropertyValue('--total-scale-factor')).toBe('1.5')
    expect(box.style.left).toBe('85.5px')
    expect(renders).toHaveBeenCalledTimes(1)

    // And once the width settles, it is redrawn at the new scale
    await waitFor(() => expect(renders).toHaveBeenCalledTimes(2))
    const [{ viewport }] = renders.mock.lastCall as [{ viewport: { scale: number } }]
    expect(viewport.scale).toBe(1.5)
  })

  it('given a page number, when asked for, then the book scrolls to it', async () => {
    // Given the book, open
    const { rerender } = render(book({ excerpt: null }))
    await screen.findByText('p. 1')

    // When a page is asked for
    rerender(book({ excerpt: null, jumpTo: { page: 186, nth: 1 } }))

    // Then the reader is taken there
    expect(Element.prototype.scrollIntoView)
      .toHaveBeenCalledWith({ block: 'start' })
  })

  it('given the same page twice, when asked for again, then it still scrolls', async () => {
    // Given the book already scrolled to a page
    const { rerender } = render(book({ excerpt: null, jumpTo: { page: 186, nth: 1 } }))
    await screen.findByText('p. 1')
    vi.mocked(Element.prototype.scrollIntoView).mockClear()

    // When the same page is asked for again, under a new count
    rerender(book({ excerpt: null, jumpTo: { page: 186, nth: 2 } }))

    // Then the request is not swallowed as a no-op
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
  })
})

describe('verticalScroller', () => {
  it('given a page in a scrolling pane, when asked, then the pane is found', () => {
    // Given a page nested two deep inside something that scrolls
    const pane = document.createElement('div')
    pane.style.overflowY = 'auto'
    const list = document.createElement('div')
    const page = document.createElement('figure')
    list.append(page)
    pane.append(list)
    document.body.append(pane)

    // When the page asks what it scrolls inside
    // Then it is the pane, not the list it sits in
    expect(verticalScroller(page)).toBe(pane)
  })

  it('given nothing that scrolls, when asked, then there is no pane', () => {
    // Given a page with no scrolling ancestor
    const page = document.createElement('figure')
    document.body.append(page)

    // When it asks
    // Then it is told so rather than handed the body
    expect(verticalScroller(page)).toBeNull()
  })
})

describe('usePan', () => {
  it('given Space held, when the page is dragged, then both axes follow', async () => {
    // Given a page zoomed past the panel, with Space held
    const { pane, container } = inAPane()
    await screen.findByText('p. 186')
    const page = pageOf(container)
    pane.scrollTop = 400
    fireEvent.keyDown(window, { code: 'Space' })
    const was = { left: page.scrollLeft, top: pane.scrollTop }

    // When it is dragged up and to the left
    fireEvent.pointerDown(page, { button: 0, clientX: 200, clientY: 200 })
    fireEvent.pointerMove(window, { clientX: 150, clientY: 130 })

    // Then the page moves under the pointer, in both axes at once
    expect(page.scrollLeft).toBe(was.left + 50)
    expect(pane.scrollTop).toBe(was.top + 70)
    // And the drag itself is not allowed to select what it crosses
    expect(document.body.classList.contains('panning')).toBe(true)
  })

  it('given no Space, when the page is dragged, then the text is selected instead', async () => {
    // Given a page with nothing arming the hand
    const { pane, container } = inAPane()
    await screen.findByText('p. 186')
    const page = pageOf(container)
    const was = { left: page.scrollLeft, top: pane.scrollTop }

    // When a plain primary drag crosses it
    fireEvent.pointerDown(page, { button: 0, clientX: 200, clientY: 200 })
    fireEvent.pointerMove(window, { clientX: 150, clientY: 130 })

    // Then nothing was panned
    expect(page.scrollLeft).toBe(was.left)
    expect(pane.scrollTop).toBe(was.top)
  })

  it('given the middle button, when the page is dragged, then it pans without Space', async () => {
    // Given a page and no key held
    const { pane, container } = inAPane()
    await screen.findByText('p. 186')
    const page = pageOf(container)
    const was = { left: page.scrollLeft, top: pane.scrollTop }

    // When it is dragged with the middle button
    fireEvent.pointerDown(page, { button: 1, clientX: 200, clientY: 200 })
    fireEvent.pointerMove(window, { clientX: 190, clientY: 180 })

    // Then that is the second way in
    expect(page.scrollLeft).toBe(was.left + 10)
    expect(pane.scrollTop).toBe(was.top + 20)
  })

  it('given a finished drag, when the pointer moves again, then the page stays put', async () => {
    // Given a drag that has been let go of
    const { pane, container } = inAPane()
    await screen.findByText('p. 186')
    const page = pageOf(container)
    const was = { left: page.scrollLeft, top: pane.scrollTop }
    fireEvent.pointerDown(page, { button: 1, clientX: 200, clientY: 200 })
    fireEvent.pointerMove(window, { clientX: 190, clientY: 190 })
    fireEvent.pointerUp(window)

    // When the pointer keeps moving across the window
    fireEvent.pointerMove(window, { clientX: 20, clientY: 20 })

    // Then the page is where it was left
    expect(page.scrollLeft).toBe(was.left + 10)
    expect(pane.scrollTop).toBe(was.top + 10)
    expect(document.body.classList.contains('panning')).toBe(false)
  })
})

describe('useSpaceHeld', () => {
  it('given Space, when it is held and released, then the hand comes and goes', async () => {
    // Given the page
    const { container } = inAPane()
    await screen.findByText('p. 186')
    const pdf = container.querySelector('.pdf') as HTMLElement

    // When Space goes down and up again
    fireEvent.keyDown(window, { code: 'Space' })
    const armed = pdf.classList.contains('grabbable')
    fireEvent.keyUp(window, { code: 'Space' })

    // Then the hand is offered only while it is held
    expect(armed).toBe(true)
    expect(pdf.classList.contains('grabbable')).toBe(false)
  })

  it('given a window losing focus, when Space was held, then the hand is dropped', async () => {
    // Given Space held
    const { container } = inAPane()
    await screen.findByText('p. 186')
    const pdf = container.querySelector('.pdf') as HTMLElement
    fireEvent.keyDown(window, { code: 'Space' })

    // When the window loses focus mid-hold
    fireEvent.blur(window)

    // Then the cursor does not stay a hand for ever
    expect(pdf.classList.contains('grabbable')).toBe(false)
  })

  it('given a space typed into a field, when it is pressed, then nothing is armed', async () => {
    // Given the page open beside somewhere to type
    const { container } = inAPane()
    await screen.findByText('p. 186')
    const field = document.createElement('input')
    document.body.append(field)

    // When a space is typed into the field
    fireEvent.keyDown(field, { code: 'Space' })

    // Then the page is not armed by it
    expect(container.querySelector('.pdf')!.classList.contains('grabbable'))
      .toBe(false)
  })
})

describe('useSelecting', () => {
  it('given a rendered page, when the text layer is built, then it ends in a catch-all', async () => {
    // Given a page whose text layer has been built
    const { container } = inAPane()
    await waitFor(() => expect(textLayer).toHaveBeenCalled())

    // When the layer is inspected
    const layer = pageOf(container).querySelector('.textLayer') as HTMLElement

    // Then the block is there, and it is the last thing in it
    await waitFor(() =>
      expect(layer.lastElementChild).toHaveClass('endOfContent'))
  })

  it('given a drag, when it starts and ends, then the catch-all covers the page for its length', async () => {
    // Given a page with a text layer
    const { container } = inAPane()
    await waitFor(() => expect(textLayer).toHaveBeenCalled())
    const layer = pageOf(container).querySelector('.textLayer') as HTMLElement

    // When a drag starts on it and then ends
    fireEvent.pointerDown(layer, { button: 0, clientX: 100, clientY: 100 })
    const during = layer.classList.contains('selecting')
    fireEvent.pointerUp(window)

    // Then the block is raised over the page only while the pointer is down
    expect(during).toBe(true)
    expect(layer.classList.contains('selecting')).toBe(false)
  })

  it('given a window losing focus, when a drag was running, then the catch-all drops', async () => {
    // Given a drag in progress
    const { container } = inAPane()
    await waitFor(() => expect(textLayer).toHaveBeenCalled())
    const layer = pageOf(container).querySelector('.textLayer') as HTMLElement
    fireEvent.pointerDown(layer, { button: 0, clientX: 100, clientY: 100 })

    // When the window loses focus
    fireEvent.blur(window)

    // Then the page is not left with a block over it
    expect(layer.classList.contains('selecting')).toBe(false)
  })
})
