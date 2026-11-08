import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '../api'
import type { ToolCall } from '../api'
import { ToolTrace } from './ToolTrace'

vi.mock('../api', () => ({
  loadLookup: vi.fn(() => Promise.resolve(
    { id: 't1', name: 'search_srd', content: '[11.2.114] Prone [Condition]',
      truncated: false })),
}))

beforeEach(() => { vi.mocked(api.loadLookup).mockClear() })

const call = (overrides: Partial<ToolCall> = {}): ToolCall => ({
  id: 't1', name: 'search_srd', args: { query: 'Prone condition' },
  done: true, status: 'ok', summary: '3 passages', ...overrides,
})

const row = () => screen.getByRole('listitem')

/** Render with a thread id, which makes rows openable. */
const trace = (tools: ToolCall[], props = {}) =>
  render(<ToolTrace tools={tools} threadId="t" {...props} />)

describe('ToolTrace', () => {
  it('given no lookups, when rendered, then nothing is drawn', () => {
    // Given a turn that searched nothing
    const { container } = render(<ToolTrace tools={[]} />)

    // When it is rendered
    // Then there is no empty box where a trace would be
    expect(container).toBeEmptyDOMElement()
  })

  it('given a search, when rendered, then it says what was searched for', () => {
    // Given one completed search
    render(<ToolTrace tools={[call()]} />)

    // When the trace is read
    // Then the query is quoted back, under a readable label
    expect(within(row()).getByText('Searched the SRD')).toBeInTheDocument()
    expect(within(row()).getByText('“Prone condition”')).toBeInTheDocument()
  })

  it('given a finished call, when rendered, then what came back is shown', () => {
    // Given a search that found three passages
    render(<ToolTrace tools={[call()]} />)

    // When the row is read
    // Then the result is on it
    expect(within(row()).getByText('3 passages')).toBeInTheDocument()
  })

  it('given a filtered search, when rendered, then the filter is shown too', () => {
    // Given a search narrowed to one entity type
    render(<ToolTrace tools={[call({ args: { query: 'fire',
                                             entity_type: 'spell' } })]} />)

    // When the trace is read
    // Then the narrowing is visible, since it changes what was found
    expect(row()).toHaveTextContent('· spell')
  })

  it('given a section read, when rendered, then the heading is what is shown', () => {
    // Given the tool that fetches one section
    render(<ToolTrace tools={[call({ name: 'get_srd_section',
                                     args: { section_id: '10.3.165' },
                                     subject: 'Countercharm',
                                     summary: '10.3.165' })]} />)

    // When the trace is read
    // Then the section is named, and its id is the outcome
    expect(within(row()).getByText('Read section')).toBeInTheDocument()
    expect(row().querySelector('.asked')).toHaveTextContent('Countercharm')
    expect(row().querySelector('.outcome')).toHaveTextContent('10.3.165')
  })

  it('given a graph walk, when rendered, then the node is named rather than numbered', () => {
    // Given a walk reached by a dotted id
    render(<ToolTrace tools={[call({ name: 'explore_srd_graph',
                                     args: { section_id: '11.2.70' },
                                     subject: 'Frightened [Condition]',
                                     summary: '24 edges' })]} />)

    // When the row is read
    // Then it says what was explored, not the number it was reached by
    expect(row().querySelector('.asked'))
      .toHaveTextContent('Frightened [Condition]')
    expect(row().querySelector('.outcome')).toHaveTextContent('24 edges')
  })

  it('given a section read still running, when rendered, then the id stands in', () => {
    // Given a fetch whose heading has not arrived yet
    render(<ToolTrace tools={[call({ name: 'get_srd_section', done: false,
                                     args: { section_id: '10.3.165' },
                                     status: undefined, summary: undefined,
                                     subject: undefined })]} />)

    // When the row is read
    // Then the id is shown rather than an empty line
    expect(row().querySelector('.asked')).toHaveTextContent('10.3.165')
    expect(row().querySelector('.outcome')).toHaveTextContent('')
  })

  it('given a replayed turn, when rendered, then the trace starts folded away', async () => {
    // Given a conversation read back rather than watched
    trace([call()], { replayed: true })

    // When it is first drawn
    // Then the rows are away, and the count says what is behind the toggle
    expect(screen.queryByRole('listitem')).toBeNull()
    expect(screen.getByRole('button')).toHaveTextContent('1 lookup')

    // And it opens on being asked
    await userEvent.click(screen.getByRole('button'))
    expect(screen.getByRole('listitem')).toBeInTheDocument()
  })

  it('given a live turn, when rendered, then the trace is open', () => {
    // Given a turn as it happens
    render(<ToolTrace tools={[call()]} />)

    // When it is first drawn
    // Then the retrieval is on show, which is the whole point during a turn
    expect(screen.getByRole('listitem')).toBeInTheDocument()
  })

  it('given a graph query, when rendered, then the cypher is flat and unquoted', () => {
    // Given a multi-line Cypher query, as the model writes it
    render(<ToolTrace tools={[call({ name: 'query_srd_graph', args: {
      cypher_query: 'MATCH (c:Creature)\n  -[:HAS_ABILITY]->(a)\nRETURN c.id',
    }, summary: '12 rows' })]} />)

    // When the trace is read
    // Then it is one line, unquoted, beside its row count
    expect(row().querySelector('.asked')).toHaveTextContent(
      'MATCH (c:Creature) -[:HAS_ABILITY]->(a) RETURN c.id')
    expect(row().querySelector('.outcome')).toHaveTextContent('12 rows')
  })

  it('given a query row, when clicked, then the whole query is shown as written', async () => {
    // Given a query whose inline form is only as much as fits
    const cypher = 'MATCH (c:Creature)\n  -[:HAS_ABILITY]->(a)\nRETURN c.id'
    trace([call({ name: 'query_srd_graph', args: { cypher_query: cypher } })])

    // When the row is opened
    const line = within(row()).getByRole('button')
    expect(line).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(line)

    // Then the query is there with its own line breaks kept
    expect(line).toHaveAttribute('aria-expanded', 'true')
    const shown = row().querySelector('.detail pre')
    expect(shown).toHaveTextContent('-[:HAS_ABILITY]->(a)')
    expect(shown?.textContent).toContain('\n')
  })

  it('given an open row, when clicked again, then it closes', async () => {
    // Given an opened row
    trace([call({ name: 'query_srd_graph',
                  args: { cypher_query: 'MATCH (n) RETURN n' } })])
    const line = within(row()).getByRole('button')
    await userEvent.click(line)

    // When it is clicked again
    await userEvent.click(line)

    // Then it is put away rather than left open under the answer
    expect(row().querySelector('.detail')).toBeNull()
  })

  it('given a finished row, when clicked, then it shows what came back', async () => {
    // Given a finished search in a conversation
    trace([call()])

    // When its row is opened
    await userEvent.click(within(row()).getByRole('button'))

    // Then the result is fetched and shown under it
    await waitFor(() => expect(row().querySelector('.detail'))
      .toHaveTextContent('[11.2.114] Prone [Condition]'))
    expect(api.loadLookup).toHaveBeenCalledWith('t', 't1')
  })

  it('given a query row, when opened, then the query leads and the result follows', async () => {
    // Given a finished query
    trace([call({ name: 'query_srd_graph',
                  args: { cypher_query: 'MATCH (n)\nRETURN n' } })])

    // When its row is opened
    await userEvent.click(within(row()).getByRole('button'))

    // Then both halves are labelled, in that order
    const labels = [...row().querySelectorAll('.detail-label')]
      .map((node) => node.textContent)
    expect(labels).toEqual(['query', 'result'])
  })

  it('given a row opened twice, when reopened, then it is not fetched again', async () => {
    // Given a row that has been opened and closed
    trace([call()])
    const line = within(row()).getByRole('button')
    await userEvent.click(line)
    await waitFor(() => expect(api.loadLookup).toHaveBeenCalledTimes(1))
    await userEvent.click(line)

    // When it is opened again
    await userEvent.click(line)

    // Then the result it already has is shown rather than re-requested
    await waitFor(() => expect(row().querySelector('.detail'))
      .toHaveTextContent('Prone'))
    expect(api.loadLookup).toHaveBeenCalledTimes(1)
  })

  it('given a result that cannot be read back, when opened, then it says so', async () => {
    // Given a server that will not return the result
    vi.mocked(api.loadLookup).mockRejectedValueOnce(new Error('404'))
    trace([call()])

    // When the row is opened
    await userEvent.click(within(row()).getByRole('button'))

    // Then the failure is named rather than drawn as an empty result
    await waitFor(() => expect(row().querySelector('.detail'))
      .toHaveTextContent('could not be read back'))
  })

  it('given a running call, when rendered, then there is nothing to open yet', () => {
    // Given a call still in flight
    trace([call({ done: false, status: undefined, summary: undefined })])

    // When the row is read
    // Then it is not a control, since it has returned nothing to show
    expect(within(row()).queryByRole('button')).toBeNull()
  })

  it('given no conversation yet, when rendered, then rows do not offer to open', () => {
    // Given a trace with no thread behind it
    render(<ToolTrace tools={[call()]} />)

    // When the row is read
    // Then it promises nothing it cannot deliver
    expect(within(row()).queryByRole('button')).toBeNull()
  })

  it('given the four tools, when rendered, then each carries its own marker', () => {
    // Given one call to each tool
    render(<ToolTrace tools={[
      call({ id: 'a', name: 'search_srd' }),
      call({ id: 'b', name: 'get_srd_section', args: { section_id: '1.1' } }),
      call({ id: 'c', name: 'explore_srd_graph', args: { section_id: '1.1' } }),
      call({ id: 'd', name: 'query_srd_graph', args: { cypher_query: 'MATCH (n)' } }),
    ]} />)

    // When the markers are read
    const marks = screen.getAllByRole('listitem')
      .map((item) => item.querySelector('.mark')?.textContent)

    // Then no two operations look the same
    expect(new Set(marks).size).toBe(4)
  })

  it('given a refused call, when rendered, then it does not read as success', () => {
    // Given a query the guard refused
    render(<ToolTrace tools={[call({ name: 'query_srd_graph',
                                     args: { cypher_query: 'CALL dbms.listConfig()' },
                                     status: 'refused', summary: 'refused' })]} />)

    // When the row is read
    // Then it is marked as refused, and says so
    expect(row()).toHaveClass('is-refused')
    expect(within(row()).getByText('refused')).toBeInTheDocument()
  })

  it('given a call that found nothing, when rendered, then it is not a failure', () => {
    // Given a query that ran and matched nothing
    render(<ToolTrace tools={[call({ name: 'query_srd_graph',
                                     args: { cypher_query: 'MATCH (n:Nope) RETURN n' },
                                     status: 'empty', summary: 'no rows' })]} />)

    // When the row is read
    // Then the emptiness is reported without being marked as broken
    expect(row()).toHaveClass('is-empty')
    expect(row()).not.toHaveClass('is-failed')
    expect(within(row()).getByText('no rows')).toBeInTheDocument()
  })

  it('given a call still running, when rendered, then it is marked as running', () => {
    // Given a search that has started but not finished
    render(<ToolTrace tools={[call({ done: false, status: undefined,
                                     summary: undefined })]} />)

    // When its row is read
    // Then it is marked running rather than looking finished
    expect(row()).toHaveClass('running')
  })

  it('given a running call, when rendered, then no outcome is claimed for it', () => {
    // Given a call whose result has not arrived
    render(<ToolTrace tools={[call({ done: false, status: undefined,
                                     summary: undefined })]} />)

    // When the row is read
    // Then the outcome is blank rather than guessed at
    expect(row().querySelector('.outcome')).toHaveTextContent('')
  })

  it('given a finished call, when rendered, then it is marked as done', () => {
    // Given a completed search
    render(<ToolTrace tools={[call()]} />)

    // When its row is read
    // Then it is marked done
    expect(row()).toHaveClass('done')
  })

  it('given several lookups, when counted, then the label is pluralised', () => {
    // Given two lookups
    render(<ToolTrace tools={[call(), call({ id: 't2' })]} />)

    // When the toggle is read
    // Then it counts them in English
    expect(screen.getByRole('button')).toHaveTextContent('2 lookups')
  })

  it('given one lookup, when counted, then the label is singular', () => {
    // Given a single lookup
    render(<ToolTrace tools={[call()]} />)

    // When the toggle is read
    // Then it does not say "1 lookups"
    expect(screen.getByRole('button')).toHaveTextContent('1 lookup')
  })

  it('given the trace, when collapsed, then the rows are hidden and can return', async () => {
    // Given an open trace
    render(<ToolTrace tools={[call()]} />)

    // When it is collapsed and opened again
    await userEvent.click(screen.getByRole('button'))
    expect(screen.queryByRole('listitem')).toBeNull()
    await userEvent.click(screen.getByRole('button'))

    // Then the retrieval is on show again
    expect(screen.getByRole('listitem')).toBeInTheDocument()
  })

  it('given an unknown tool, when rendered, then its own name is used', () => {
    // Given a tool this component has no label for
    render(<ToolTrace tools={[call({ name: 'cypher', args: {} })]} />)

    // When the trace is read
    // Then it still says something rather than nothing
    expect(within(row()).getByText('cypher')).toBeInTheDocument()
  })
})
