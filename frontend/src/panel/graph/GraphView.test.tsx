import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { GraphEdge, GraphNode, Neighbourhood } from '../../api'
import { GraphView } from './GraphView'

vi.mock('../../api', () => ({ loadNeighbourhood: vi.fn() }))
const api = await import('../../api')

const node = (uid: string, overrides: Partial<GraphNode> = {}): GraphNode => ({
  uid, name: uid, labels: ['Rule'], entity_type: 'rule',
  section_id: uid, page: 1, summary: null, facts: [], degree: 3, depth: 1,
  ...overrides,
})

const edge = (uid: string, source: string, target: string,
              type = 'HAS_SUBSECTION'): GraphEdge => ({ uid, type, source, target })

const graph = (overrides: Partial<Neighbourhood> = {}): Neighbourhood => ({
  root: 'root',
  nodes: [node('root', { name: 'Prone [Condition]', labels: ['Condition'],
                          depth: 0 }),
          node('a', { name: 'Grappled' })],
  edges: [edge('e1', 'root', 'a')],
  truncated: [],
  ...overrides,
})

describe('GraphView', () => {
  beforeEach(() => {
    vi.mocked(api.loadNeighbourhood).mockImplementation(() =>
      Promise.resolve(graph()))
  })

  it('given nothing cited, when rendered, then the book is fetched instead', async () => {
    // Given a panel with no citation
    render(<GraphView sectionId={null} depth={2} onOpenPage={vi.fn()} />)

    // When the view opens
    // Then the seed is the book, at the chosen depth
    await waitFor(() => expect(api.loadNeighbourhood)
      .toHaveBeenCalledWith(null, 2))
  })

  it('given a citation, when rendered, then the neighbourhood is fetched for it', async () => {
    // Given a cited section
    render(<GraphView sectionId="11.2.114" depth={2} onOpenPage={vi.fn()} />)

    // When the view opens
    // Then the seed is the citation, at the chosen depth
    await waitFor(() => expect(api.loadNeighbourhood)
      .toHaveBeenCalledWith({ section: '11.2.114' }, 2))
  })

  it('given a neighbourhood, when drawn, then every node is named on the canvas', async () => {
    // Given a graph of two nodes
    render(<GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)

    // When it is drawn
    // Then both are labelled
    expect(await screen.findByText('Grappled')).toBeInTheDocument()
    expect(screen.getAllByText('Prone [Condition]').length).toBeGreaterThan(0)
  })

  it('given a node, when selected, then the card says what it is', async () => {
    // Given a drawn graph whose neighbour carries prose
    vi.mocked(api.loadNeighbourhood).mockImplementation(() =>
      Promise.resolve(graph({
        nodes: [node('root', { name: 'Prone [Condition]', depth: 0 }),
                node('a', { name: 'Grappled',
                            summary: 'Your Speed becomes 0.' })] })))
    render(<GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)

    // When a node is selected
    await userEvent.click(await screen.findByText('Grappled'))

    // Then the answer arrives with the node, costing no request
    expect(await screen.findByText('Your Speed becomes 0.')).toBeInTheDocument()
  })

  it('given a selected section, when the page is opened, then the panel is told', async () => {
    // Given a selected node that is a section
    const onOpenPage = vi.fn()
    render(<GraphView sectionId="11.2.114" depth={1} onOpenPage={onOpenPage} />)
    await userEvent.click(await screen.findByText('Grappled'))

    // When its page is opened
    await userEvent.click(screen.getByRole('button', { name: 'Open page' }))

    // Then the reader is taken to the passage, not to another picture
    expect(onOpenPage).toHaveBeenCalledWith('a')
  })

  it('given a derived node, when selected, then no page is offered', async () => {
    // Given a neighbour that is not a section
    vi.mocked(api.loadNeighbourhood).mockImplementation(() =>
      Promise.resolve(graph({
        nodes: [node('root', { depth: 0 }),
                node('a', { name: 'Poison', section_id: null,
                            labels: ['DamageType'] })] })))
    render(<GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)

    // When it is selected
    await userEvent.click(await screen.findByText('Poison'))

    // Then there is no page to open
    expect(screen.queryByRole('button', { name: 'Open page' })).toBeNull()
  })

  it('given a failing request, when rendered, then the reason is shown', async () => {
    // Given a server that cannot answer
    vi.mocked(api.loadNeighbourhood).mockImplementationOnce(async () => {
      throw new Error('503 unavailable')
    })

    // When the view opens
    render(<GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)

    // Then the failure is on screen rather than an empty canvas
    expect(await screen.findByText(/503 unavailable/)).toBeInTheDocument()
  })

  it('given a new citation, when it arrives, then the picture is reseeded', async () => {
    // Given one citation drawn
    const { rerender } = render(
      <GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)
    await screen.findByText('Prone [Condition]')

    // When another citation is opened
    rerender(<GraphView sectionId="11.2.120" depth={1} onOpenPage={vi.fn()} />)

    // Then the graph is asked for again, seeded on the new one
    await waitFor(() => expect(api.loadNeighbourhood)
      .toHaveBeenLastCalledWith({ section: '11.2.120' }, 1))
  })
})
