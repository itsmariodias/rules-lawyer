/**
 * What the agent looked up, shown while it looks it up.
 *
 * During a slow first token this is the only sign the thing is alive, so
 * what matters is that a call appears the moment it starts and is marked
 * finished when it ends.
 */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { ToolCall } from '../api'
import { ToolTrace } from './ToolTrace'

const call = (overrides: Partial<ToolCall> = {}): ToolCall => ({
  id: 't1', name: 'search_srd', args: { query: 'Prone condition' },
  done: true, ...overrides,
})

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
    expect(screen.getByText(/Searched the SRD: “Prone condition”/))
      .toBeInTheDocument()
  })

  it('given a filtered search, when rendered, then the filter is shown too', () => {
    // Given a search narrowed to one entity type
    render(<ToolTrace tools={[call({ args: { query: 'fire',
                                             entity_type: 'spell' } })]} />)

    // When the trace is read
    // Then the narrowing is visible, since it changes what was found
    expect(screen.getByText(/“fire” · spell/)).toBeInTheDocument()
  })

  it('given a section read, when rendered, then it names the section', () => {
    // Given the other tool the agent may call
    render(<ToolTrace tools={[call({ name: 'get_srd_section',
                                     args: { section_id: '11.2.114' } })]} />)

    // When the trace is read
    // Then it reads as what it did, not as a function name
    expect(screen.getByText(/Read section: “11.2.114”/)).toBeInTheDocument()
  })

  it('given a graph walk, when rendered, then it names the section walked from', () => {
    // Given the third tool, which reads edges rather than prose
    render(<ToolTrace tools={[call({ name: 'explore_srd_graph',
                                     args: { section_id: '11.2.114' } })]} />)

    // When the trace is read
    // Then it is distinguishable from a search of the same section
    expect(screen.getByText(/Explored the graph: “11.2.114”/))
      .toBeInTheDocument()
  })

  it('given a graph query, when rendered, then the cypher is flattened to one line', () => {
    // Given a multi-line Cypher query, as the model writes it
    render(<ToolTrace tools={[call({ name: 'query_srd_graph', args: {
      cypher_query: 'MATCH (c:Creature)\n  -[:HAS_ABILITY]->(a)\nRETURN c.id',
    } })]} />)

    // When the trace is read
    // Then it is one line, not the height of the query
    expect(screen.getByText(
      /Queried the graph: “MATCH \(c:Creature\) -\[:HAS_ABILITY\]->\(a\) RETURN c.id”/,
    )).toBeInTheDocument()
  })

  it('given a long query, when rendered, then it is cut rather than wrapped', () => {
    // Given a query longer than the trace has room for
    render(<ToolTrace tools={[call({ name: 'query_srd_graph', args: {
      cypher_query: `MATCH (n:Section) WHERE n.id = '${'x'.repeat(200)}' RETURN n`,
    } })]} />)

    // When the trace is read
    // Then it ends in an ellipsis
    expect(screen.getByText(/…”$/)).toBeInTheDocument()
  })

  it('given a call still running, when rendered, then it is marked as running', () => {
    // Given a search that has started but not finished
    render(<ToolTrace tools={[call({ done: false })]} />)

    // When its row is read
    // Then it is marked running rather than looking finished
    expect(screen.getByRole('listitem')).toHaveClass('running')
  })

  it('given a finished call, when rendered, then it is marked as done', () => {
    // Given a completed search
    render(<ToolTrace tools={[call()]} />)

    // When its row is read
    // Then it is marked done
    expect(screen.getByRole('listitem')).toHaveClass('done')
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
    expect(screen.getByText('cypher')).toBeInTheDocument()
  })
})
