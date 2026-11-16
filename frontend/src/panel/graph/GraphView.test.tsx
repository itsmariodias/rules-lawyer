import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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

/** The root's out-edges cut by the fan: one drawn of nine. */
const cut = graph({ truncated: [{ uid: 'root', type: 'HAS_SUBSECTION',
                                  direction: 'out', total: 9, shown: 1 }] })

/** The drawn picture's pan and zoom, read from its transform. */
function camera(container: HTMLElement) {
  const transform = container.querySelector('svg > g')!.getAttribute('transform')!
  const [, x, y, k] = transform.match(/translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+)\)/)!
  return { x: Number(x), y: Number(y), k: Number(k) }
}

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

  it('given a node with edges not fetched, when selected, then the card counts them', async () => {
    // Given a seed whose subsections were cut by the fan
    vi.mocked(api.loadNeighbourhood).mockResolvedValue(cut)

    // When its card is shown, as the seed's is on opening
    const { container } = render(
      <GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)

    // Then it says how many exist and how many are drawn, and the node
    // carries a halo saying there is more
    expect(await screen.findByText(/8 not fetched/)).toBeInTheDocument()
    expect(screen.getByText('1 of 9')).toBeInTheDocument()
    await waitFor(() =>
      expect(container.querySelector('circle.more')).not.toBeNull())
  })

  it('given a cut node, when expanded, then its neighbours join the picture', async () => {
    // Given a seed with edges not fetched, and a server that sends them
    vi.mocked(api.loadNeighbourhood).mockImplementation(async (seed) =>
      seed && 'node' in seed
        ? graph({ nodes: [node('root', { depth: 0 }), node('a'),
                          node('b', { name: 'Restrained' })],
                  edges: [edge('e1', 'root', 'a'), edge('e2', 'root', 'b')] })
        : cut)
    render(<GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)
    await screen.findByText(/8 not fetched/)

    // When it is expanded
    await userEvent.click(screen.getByRole('button', { name: 'Expand' }))

    // Then the node is asked for with at least the default fan, the new
    // neighbour is drawn beside the old, and nothing is left to fetch
    expect(api.loadNeighbourhood).toHaveBeenLastCalledWith({ node: 'root' }, 1, 8)
    expect(await screen.findByText('Restrained')).toBeInTheDocument()
    expect(screen.getByText('Grappled')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expanded' })).toBeDisabled()
  })

  it('given an expansion that fails, when asked, then the reason is shown', async () => {
    // Given a drawn graph and a server that then refuses
    render(<GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)
    await screen.findByText('Grappled')
    vi.mocked(api.loadNeighbourhood).mockRejectedValueOnce(new Error('503 unavailable'))

    // When a node is expanded
    await userEvent.click(screen.getByRole('button', { name: 'Expand' }))

    // Then the failure is said, and the picture that was there stays
    expect(await screen.findByText(/503 unavailable/)).toBeInTheDocument()
    expect(screen.getByText('Grappled')).toBeInTheDocument()
  })

  it('given a node with no prose, when selected, then its properties are listed', async () => {
    // Given a weapon row, which has properties but no passage of its own
    vi.mocked(api.loadNeighbourhood).mockResolvedValue(graph({
      nodes: [node('root', { depth: 0 }),
              node('a', { name: 'Longsword', section_id: null,
                          labels: ['Equipment', 'Weapon'],
                          facts: [{ name: 'cost', value: '15 GP' }] })] }))
    render(<GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)

    // When it is selected
    await userEvent.click(await screen.findByText('Longsword'))

    // Then what is known about it is shown instead of a summary
    expect(screen.getByText('cost')).toBeInTheDocument()
    expect(screen.getByText('15 GP')).toBeInTheDocument()
  })

  it('given a drawn graph, when the wheel turns, then it zooms', async () => {
    // Given a drawn graph
    const { container } = render(
      <GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)
    await screen.findByText('Grappled')
    const canvas = container.querySelector('.graph-canvas')!
    const before = camera(container).k

    // When the wheel turns towards the reader
    fireEvent.wheel(canvas, { deltaY: -200, clientX: 100, clientY: 100 })

    // Then the picture is closer
    expect(camera(container).k).toBeGreaterThan(before)
  })

  it('given a drawn graph, when the background is dragged, then the picture follows', async () => {
    // Given a drawn graph, its view taken by a press on the background
    const { container } = render(
      <GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)
    await screen.findByText('Grappled')
    const canvas = container.querySelector('.graph-canvas')!
    fireEvent.pointerDown(canvas, { clientX: 100, clientY: 100 })
    const before = camera(container)

    // When the pointer moves
    fireEvent.pointerMove(window, { clientX: 150, clientY: 130 })
    fireEvent.pointerUp(window)

    // Then the picture moved with it, at the same zoom
    expect(camera(container)).toEqual({ x: before.x + 50, y: before.y + 30,
                                        k: before.k })
  })

  it('given a zoomed view, when Fit is pressed, then the view is handed back', async () => {
    // Given a view zoomed far in by the reader
    const { container } = render(
      <GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)
    await screen.findByText('Grappled')
    fireEvent.wheel(container.querySelector('.graph-canvas')!, { deltaY: -2000 })
    expect(camera(container).k).toBe(3)

    // When Fit is pressed
    await userEvent.click(screen.getByRole('button', { name: 'Fit' }))

    // Then the zoom is the fitted one again, which never passes 1.5
    expect(camera(container).k).toBeLessThanOrEqual(1.5)
  })

  it('given a settled layout, when a node is dragged, then it follows the pointer', async () => {
    // Given a graph whose simulation has cooled and stopped
    vi.useFakeTimers()
    try {
      const { container } = render(
        <GraphView sectionId="11.2.114" depth={1} onOpenPage={vi.fn()} />)
      // The load commits first: only then is the first frame asked for.
      await act(() => vi.advanceTimersByTimeAsync(0))
      // About 690 frames of 16ms cool it below COLD.
      await act(() => vi.advanceTimersByTimeAsync(15_000))
      const leaf = screen.getByText('Grappled').closest('g')!
      const settled = leaf.getAttribute('transform')

      // When the node is dragged across the canvas
      fireEvent.pointerDown(leaf, { clientX: 10, clientY: 10 })
      fireEvent.pointerMove(window, { clientX: 400, clientY: 300 })
      await act(() => vi.advanceTimersByTimeAsync(100))
      fireEvent.pointerUp(window)

      // Then it is drawn under the pointer, in the picture's own units
      const view = camera(container)
      const [, x, y] = leaf.getAttribute('transform')!
        .match(/translate\(([-\d.]+),([-\d.]+)\)/)!.map(Number)
      expect(leaf.getAttribute('transform')).not.toBe(settled)
      expect(x).toBeCloseTo((400 - view.x) / view.k)
      expect(y).toBeCloseTo((300 - view.y) / view.k)
    } finally {
      vi.useRealTimers()
    }
  })
})
