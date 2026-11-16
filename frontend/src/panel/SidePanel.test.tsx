/** pdf.js and the graph view are mocked. */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SourceExcerpt } from '../api'
import { SidePanel } from './SidePanel'

vi.mock('../api', () => ({ loadSource: vi.fn() }))
vi.mock('./graph/GraphView', () => ({
  GraphView: ({ sectionId, depth }: { sectionId: string | null; depth: number }) =>
    <div data-testid="graph">{`${sectionId ?? 'none'} at ${depth}`}</div>,
}))
vi.mock('./page/PdfPage', () => ({
  PdfPage: ({ zoom }: { zoom: number }) =>
    <div data-testid="pdf-page">{`page at ${zoom}`}</div>,
  PdfBook: ({ jumpTo }: { jumpTo: { page: number } | null }) =>
    <div data-testid="pdf-book">{jumpTo ? `book at ${jumpTo.page}` : 'book'}</div>,
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

function panel(props: Partial<Parameters<typeof SidePanel>[0]> = {}) {
  const merged = {
    sectionId: '11.2.114' as string | null, tab: 'page' as const,
    onTab: vi.fn(), onClose: vi.fn(), onNavigate: vi.fn(), ...props,
  }
  return { ...render(<SidePanel {...merged} />), props: merged }
}

beforeEach(() => vi.mocked(api.loadSource).mockResolvedValue(excerpt()))

describe('SidePanel', () => {
  it('given a citation, when opened, then its heading and id are shown', async () => {
    // Given a cited section
    panel()

    // When the panel loads it
    // Then it says which passage this is
    expect(await screen.findByRole('heading', { name: 'Prone [Condition]' }))
      .toBeInTheDocument()
    expect(screen.getByText('11.2.114')).toBeInTheDocument()
  })

  it('given a citation, when opened, then the page facsimile is drawn', async () => {
    // Given a cited section
    panel()

    // When it loads
    // Then the printed page is what is shown
    expect(await screen.findByTestId('pdf-page')).toBeInTheDocument()
  })

  it('given nothing cited, when the page tab is open, then the whole book is browsable', async () => {
    // Given a panel opened with no citation
    panel({ sectionId: null })

    // When the page tab is shown
    // Then it is the book from page one, with a way to type a page number
    expect(await screen.findByTestId('pdf-book')).toBeInTheDocument()
    expect(screen.getByLabelText('Page')).toBeInTheDocument()
  })

  it('given a page number, when submitted, then the book jumps to it', async () => {
    // Given the book with nothing cited
    panel({ sectionId: null })
    await screen.findByTestId('pdf-book')

    // When a page is typed and submitted
    await userEvent.type(screen.getByLabelText('Page'), '186')
    await userEvent.click(screen.getByRole('button', { name: 'Go' }))

    // Then the reader is taken there
    expect(screen.getByTestId('pdf-book')).toHaveTextContent('book at 186')
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
    await screen.findByTestId('pdf-page')

    // When a closer look is chosen and the panel is reopened
    await userEvent.click(screen.getByRole('button', { name: '2×' }))
    unmount()
    panel()

    // Then the page comes back at the same zoom
    expect(await screen.findByTestId('pdf-page')).toHaveTextContent('page at 2')
  })

  it('given a nested citation, when shown, then its path runs from the top of the book', async () => {
    // Given a citation two levels below a top-level section
    panel()

    // When the panel shows it
    const crumbs = await screen.findByRole('navigation',
                                           { name: 'Location in the book' })

    // Then every ancestor is listed in order, ending on the cited section
    expect(within(crumbs).getAllByRole('listitem').map((item) => item.textContent))
      .toEqual(['Rules Glossary', 'Rules Definitions', 'Prone [Condition]'])
    expect(within(crumbs).getByText('Prone [Condition]'))
      .toHaveAttribute('aria-current', 'location')
  })

  it('given any ancestor, when it is pressed, then the panel navigates to it', async () => {
    // Given a nested citation
    const { props } = panel()
    const crumbs = await screen.findByRole('navigation',
                                           { name: 'Location in the book' })

    // When the top-level section is pressed
    await userEvent.click(within(crumbs).getByRole('button',
                                                   { name: 'Rules Glossary' }))

    // Then the panel is asked to open it
    expect(props.onNavigate).toHaveBeenCalledWith('11')
  })

  it('given a top-level section, when shown, then there is no path to draw', async () => {
    // Given a citation of a top-level section
    vi.mocked(api.loadSource).mockResolvedValue(
      excerpt({ section_id: '11', heading: 'Rules Glossary', ancestors: [],
                parent: null }))
    panel({ sectionId: '11' })

    // When the panel shows it
    await screen.findByRole('heading', { name: 'Rules Glossary' })

    // Then no breadcrumb is drawn
    expect(screen.queryByRole('navigation', { name: 'Location in the book' }))
      .toBeNull()
  })

  it('given subsections, when one is pressed, then the panel navigates to it', async () => {
    // Given a citation with children
    vi.mocked(api.loadSource).mockResolvedValue(excerpt({
      children: [{ id: '11.2.115', heading: 'Restrained [Condition]' }] }))
    const { props } = panel()

    // When a subsection is pressed
    await userEvent.click(await screen.findByRole(
      'button', { name: 'Restrained [Condition]' }))

    // Then it becomes the open passage
    expect(props.onNavigate).toHaveBeenCalledWith('11.2.115')
  })

  it('given the tabs, when one is pressed, then the shell is told', async () => {
    // Given the panel on the page tab
    const { props } = panel()

    // When the graph tab is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Graph' }))

    // Then the choice goes up rather than being kept here
    expect(props.onTab).toHaveBeenCalledWith('graph')
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
    const { rerender } = panel()
    await screen.findByRole('heading', { name: 'Prone [Condition]' })

    // When a second citation is opened
    let resolve: (value: SourceExcerpt) => void = () => {}
    vi.mocked(api.loadSource).mockReturnValue(
      new Promise((r) => { resolve = r }))
    rerender(<SidePanel sectionId="11.2.120" tab="page" onTab={vi.fn()}
                        onClose={vi.fn()} onNavigate={vi.fn()} />)

    // Then the previous passage is not left up under the new id
    expect(screen.queryByRole('heading', { name: 'Prone [Condition]' }))
      .toBeNull()
    resolve(excerpt({ section_id: '11.2.120', heading: 'Restrained' }))
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Restrained' }))
        .toBeInTheDocument())
  })

  it('given two citations in quick succession, when the first answers last, then the second stays', async () => {
    // Given a first citation whose source is slow to arrive
    let first: (value: SourceExcerpt) => void = () => {}
    vi.mocked(api.loadSource).mockReturnValueOnce(
      new Promise((r) => { first = r }))
    const { rerender } = panel()

    // When a second citation is opened and answers before the first
    vi.mocked(api.loadSource).mockResolvedValueOnce(
      excerpt({ section_id: '11.2.120', heading: 'Restrained' }))
    rerender(<SidePanel sectionId="11.2.120" tab="page" onTab={vi.fn()}
                        onClose={vi.fn()} onNavigate={vi.fn()} />)
    await screen.findByRole('heading', { name: 'Restrained' })
    first(excerpt())

    // Then the late first answer does not replace the passage being read
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.getByRole('heading', { name: 'Restrained' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Prone [Condition]' })).toBeNull()
  })
})
