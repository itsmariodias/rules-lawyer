/** pdf.js and the graph view are mocked. */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SourceExcerpt } from '../api'
import { SidePanel } from './SidePanel'

vi.mock('../api', () => ({ loadSource: vi.fn(), loadNeighbourhood: vi.fn() }))
vi.mock('./graph/GraphView', () => ({
  GraphView: ({ sectionId, depth, onOpenPage }: {
    sectionId: string | null; depth: number; onOpenPage: (id: string) => void
  }) => (
    <div data-testid="graph">
      {`${sectionId ?? 'none'} at ${depth}`}
      <button onClick={() => onOpenPage('11.2.120')}>Open page</button>
    </div>
  ),
}))
vi.mock('./page/PdfPage', () => ({
  PdfBook: ({ zoom, excerpt, visit, jumpTo }: {
    zoom: number; excerpt: SourceExcerpt | null; visit: number
    jumpTo: { page: number } | null
  }) => (
    <div data-testid="pdf-book">
      {`book at ${zoom}, boxing ${excerpt?.section_id ?? 'nothing'}, ` +
       `visit ${visit}${jumpTo ? `, page ${jumpTo.page}` : ''}`}
    </div>
  ),
}))

const api = await import('../api')

const excerpt = (overrides: Partial<SourceExcerpt> = {}): SourceExcerpt => ({
  section_id: '11.2.114', heading: 'Prone [Condition]',
  entity_type: 'glossary_term', page: 186, text: 'While you have…',
  highlight: { start: 0, end: 10 }, boxes: [], pages: [186],
  ancestors: [{ id: '11', heading: 'Rules Glossary' },
              { id: '11.2', heading: 'Rules Definitions' }],
  parent: { id: '11.2', heading: 'Rules Definitions' }, children: [],
  ...overrides,
})

type PanelProps = Parameters<typeof SidePanel>[0]

function panel(props: Partial<PanelProps> = {}) {
  const merged: PanelProps = {
    sectionId: '11.2.114', visit: 1, tab: 'page',
    onTab: vi.fn(), onClose: vi.fn(), onNavigate: vi.fn(), ...props,
  }
  return { ...render(<SidePanel {...merged} />), props: merged }
}

/** The book seed's neighbourhood: the seed, then its roots out of order. */
const book = {
  root: 'book', edges: [], truncated: [],
  nodes: [
    { uid: 'book', name: 'System Reference Document 5.2.1', section_id: null, depth: 0 },
    { uid: 'b', name: 'Playing the Game', section_id: '2', depth: 1 },
    { uid: 'k', name: 'Rules Glossary', section_id: '11', depth: 1 },
    { uid: 'a', name: 'Legal Information', section_id: '1', depth: 1 },
  ],
} as unknown as Awaited<ReturnType<typeof api.loadNeighbourhood>>

const tree = () => screen.getByRole('navigation', { name: 'Location in the book' })
const current = () => within(tree()).getByText(
  (_, element) => element?.getAttribute('aria-current') === 'location')

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
  vi.mocked(api.loadSource).mockResolvedValue(excerpt())
  vi.mocked(api.loadNeighbourhood).mockResolvedValue(book)
})

describe('SidePanel', () => {
  it('given a citation, when opened, then the book boxes it under its path', async () => {
    // Given a cited section
    panel()

    // When the panel loads it
    // Then the whole book is drawn with its lines boxed, and the tree says
    // where it is
    await waitFor(() => expect(screen.getByTestId('pdf-book'))
      .toHaveTextContent('boxing 11.2.114, visit 1'))
    expect(current()).toHaveTextContent('Prone [Condition]')
    expect(within(tree()).getByRole('button', { name: 'Rules Glossary' }))
      .toBeInTheDocument()
  })

  it('given nothing cited, when the page tab is open, then the book and its sections are listed', async () => {
    // Given a panel opened with no citation
    panel({ sectionId: null })

    // When the page tab is shown
    // Then it is the book with nothing boxed, a way to type a page number,
    // and the top-level sections in book order
    expect(await screen.findByTestId('pdf-book')).toHaveTextContent('boxing nothing')
    expect(screen.getByLabelText('Page')).toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: 'Sections (3)' }))
    expect(screen.getAllByRole('menuitem').map((entry) => entry.textContent))
      .toEqual(['Legal Information', 'Playing the Game', 'Rules Glossary'])
    expect(api.loadNeighbourhood).toHaveBeenCalledWith(null, 1)
  })

  it('given the sections listed once, when the book is reopened, then they are not fetched again', async () => {
    // Given the top-level sections already shown
    const { rerender, props } = panel({ sectionId: null })
    await within(tree()).findByRole('button', { name: 'Sections (3)' })

    // When a section is cited and then cleared
    rerender(<SidePanel {...props} sectionId="11.2.114" />)
    await waitFor(() => expect(current()).toHaveTextContent('Prone [Condition]'))
    rerender(<SidePanel {...props} sectionId={null} />)

    // Then the list comes back without another request
    expect(await within(tree()).findByRole('button', { name: 'Sections (3)' }))
      .toBeInTheDocument()
    expect(api.loadNeighbourhood).toHaveBeenCalledTimes(1)
  })

  it('given the sections fail to load, when the book is open, then the reason is shown', async () => {
    // Given a graph that cannot answer
    vi.mocked(api.loadNeighbourhood).mockRejectedValue(new Error('503 unavailable'))

    // When the book opens
    panel({ sectionId: null })

    // Then the tree says why it is empty
    expect(await within(tree()).findByText(/503 unavailable/)).toBeInTheDocument()
  })

  it('given a section in the tree, when pressed, then the panel navigates to it', async () => {
    // Given a nested citation
    const { props } = panel()
    await waitFor(() => expect(current()).toHaveTextContent('Prone [Condition]'))

    // When its top-level section is pressed
    await userEvent.click(within(tree()).getByRole('button', { name: 'Rules Glossary' }))

    // Then the panel is asked to open it
    expect(props.onNavigate).toHaveBeenCalledWith('11')
  })

  it('given a citation, when SRD is pressed, then the citation clears and the book goes to page 1', async () => {
    // Given a nested citation
    const { props } = panel()
    await waitFor(() => expect(current()).toHaveTextContent('Prone [Condition]'))

    // When the first crumb, the book itself, is pressed
    await userEvent.click(within(tree()).getByRole('button', { name: 'SRD' }))

    // Then the shell is asked for the whole book, which scrolls to its start
    expect(props.onNavigate).toHaveBeenCalledWith(null)
    expect(screen.getByTestId('pdf-book')).toHaveTextContent('page 1')
  })

  it('given a citation, when another is opened, then the book is not drawn again', async () => {
    // Given one citation open
    const { rerender, props } = panel()
    await waitFor(() => expect(screen.getByTestId('pdf-book'))
      .toHaveTextContent('boxing 11.2.114'))
    const drawn = screen.getByTestId('pdf-book')

    // When a second citation is opened
    vi.mocked(api.loadSource).mockResolvedValue(
      excerpt({ section_id: '11.2.120', heading: 'Restrained' }))
    rerender(<SidePanel {...props} sectionId="11.2.120" visit={2} />)

    // Then the same book moves its boxes rather than being rebuilt
    await waitFor(() => expect(screen.getByTestId('pdf-book'))
      .toHaveTextContent('boxing 11.2.120, visit 2'))
    expect(screen.getByTestId('pdf-book')).toBe(drawn)
  })

  it('given a page number, when submitted, then the book jumps to it', async () => {
    // Given a citation open
    panel()
    await screen.findByTestId('pdf-book')

    // When a page is typed and submitted
    await userEvent.type(screen.getByLabelText('Page'), '186')
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))

    // Then the reader is taken there
    expect(screen.getByTestId('pdf-book')).toHaveTextContent('page 186')
  })

  it('given an empty page box, when read, then there is nothing to submit', () => {
    // Given the book with nothing typed
    panel({ sectionId: null })

    // When the button is read
    // Then it cannot be pressed
    expect(screen.getByRole('button', { name: 'Go' })).toBeDisabled()
  })

  it('given nothing cited, when the graph tab is open, then the depth can still be chosen', () => {
    // Given the graph tab with no citation
    panel({ sectionId: null, tab: 'graph' })

    // When the toolbar is read
    // Then the hops are offered, since the book is drawn
    expect(screen.getByRole('button', { name: '2 hops' })).toBeInTheDocument()
    expect(screen.getByTestId('graph')).toHaveTextContent('none at 1')
  })

  it('given the graph tab, when shown, then it opens on the same section', () => {
    // Given the panel on the graph tab
    panel({ tab: 'graph' })

    // When the graph is drawn
    // Then it is seeded on the citation, at the remembered depth
    expect(screen.getByTestId('graph')).toHaveTextContent('11.2.114 at 1')
  })

  it('given a depth control, when a depth is chosen, then it is remembered', async () => {
    // Given the graph tab
    const { unmount } = panel({ tab: 'graph' })

    // When two hops is chosen and the panel is opened again
    await userEvent.click(screen.getByRole('button', { name: '2 hops' }))
    expect(screen.getByTestId('graph')).toHaveTextContent('at 2')
    unmount()
    panel({ tab: 'graph' })

    // Then the choice survived
    expect(screen.getByTestId('graph')).toHaveTextContent('at 2')
  })

  it('given a zoom, when chosen, then the page is drawn at it and it is remembered', async () => {
    // Given a cited page
    const { unmount } = panel()
    await screen.findByTestId('pdf-book')

    // When a closer look is chosen and the panel is reopened
    await userEvent.click(screen.getByRole('button', { name: '2×' }))
    unmount()
    panel()

    // Then the book comes back at the same zoom
    expect(await screen.findByTestId('pdf-book')).toHaveTextContent('book at 2')
  })

  it('given the tabs, when one is pressed, then the shell is told', async () => {
    // Given the panel on the page tab
    const { props } = panel()

    // When the graph tab is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))

    // Then the choice goes up rather than being kept here
    expect(props.onTab).toHaveBeenCalledWith('graph')
  })

  it('given the graph tab, when Page is pressed, then the shell is told', async () => {
    // Given the panel on the graph tab
    const { props } = panel({ tab: 'graph' })

    // When the page tab is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Page' }))

    // Then the choice goes up
    expect(props.onTab).toHaveBeenCalledWith('page')
  })

  it('given a node in the graph, when its page is opened, then the panel turns to it', async () => {
    // Given the graph tab
    const { props } = panel({ tab: 'graph' })

    // When a node's page is opened from the graph
    await userEvent.click(screen.getByRole('button', { name: 'Open page' }))

    // Then the citation moves to that section, shown on the page tab
    expect(props.onNavigate).toHaveBeenCalledWith('11.2.120')
    expect(props.onTab).toHaveBeenCalledWith('page')
  })

  it('given the panel, when closed, then the shell is told', async () => {
    // Given an open panel
    const { props } = panel()

    // When it is closed
    await userEvent.click(screen.getByRole('button', { name: 'Close panel' }))

    // Then the shell decides what happens to the layout
    expect(props.onClose).toHaveBeenCalled()
  })

  it('given a source that fails to load, when opened, then the reason is shown', async () => {
    // Given a server that cannot answer
    vi.mocked(api.loadSource).mockImplementationOnce(async () => {
      throw new Error('503 unavailable')
    })

    // When the panel opens the citation
    panel()

    // Then the failure is on screen rather than an endless "Loading…"
    expect(await screen.findByText(/503 unavailable/)).toBeInTheDocument()
  })

  it('given a new citation, when it replaces the last, then the old one is cleared first', async () => {
    // Given one citation open
    const { rerender, props } = panel()
    await waitFor(() => expect(current()).toHaveTextContent('Prone [Condition]'))

    // When a second citation is opened
    let resolve: (value: SourceExcerpt) => void = () => {}
    vi.mocked(api.loadSource).mockReturnValue(
      new Promise((r) => { resolve = r }))
    rerender(<SidePanel {...props} sectionId="11.2.120" />)

    // Then the previous passage is not left boxed under the new id
    expect(within(tree()).queryByText('Prone [Condition]')).toBeNull()
    expect(screen.getByTestId('pdf-book')).toHaveTextContent('boxing nothing')
    expect(within(tree()).getByText('Loading…')).toBeInTheDocument()
    resolve(excerpt({ section_id: '11.2.120', heading: 'Restrained' }))
    await waitFor(() => expect(current()).toHaveTextContent('Restrained'))
  })

  it('given two citations in quick succession, when the first answers last, then the second stays', async () => {
    // Given a first citation whose source is slow to arrive
    let first: (value: SourceExcerpt) => void = () => {}
    vi.mocked(api.loadSource).mockReturnValueOnce(
      new Promise((r) => { first = r }))
    const { rerender, props } = panel()

    // When a second citation is opened and answers before the first
    vi.mocked(api.loadSource).mockResolvedValueOnce(
      excerpt({ section_id: '11.2.120', heading: 'Restrained' }))
    rerender(<SidePanel {...props} sectionId="11.2.120" />)
    await waitFor(() => expect(current()).toHaveTextContent('Restrained'))
    first(excerpt())

    // Then the late first answer does not replace the passage being read
    await new Promise((r) => setTimeout(r, 0))
    expect(current()).toHaveTextContent('Restrained')
    expect(screen.getByTestId('pdf-book')).toHaveTextContent('boxing 11.2.120')
  })

  it('given a citation that fails after a newer one opened, when it fails, then no error is shown', async () => {
    // Given a first citation whose source will fail late
    let fail: (reason: Error) => void = () => {}
    vi.mocked(api.loadSource).mockReturnValueOnce(
      new Promise((_, reject) => { fail = reject }))
    const { rerender, props } = panel()

    // When a second citation loads, then the first fails
    vi.mocked(api.loadSource).mockResolvedValueOnce(
      excerpt({ section_id: '11.2.120', heading: 'Restrained' }))
    rerender(<SidePanel {...props} sectionId="11.2.120" />)
    await waitFor(() => expect(current()).toHaveTextContent('Restrained'))
    fail(new Error('503 unavailable'))
    await new Promise((r) => setTimeout(r, 0))

    // Then the passage being read is not covered by an old failure
    expect(screen.queryByText(/503 unavailable/)).toBeNull()
  })
})
