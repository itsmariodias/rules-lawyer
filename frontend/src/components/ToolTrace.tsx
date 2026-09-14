/**
 * What the agent looked up, shown while it looks it up.
 *
 * A graph RAG answer is only trustworthy if you can see the retrieval, and
 * during a slow first token this is the only sign the thing is alive.
 */

import { useState } from 'react'
import type { ToolCall } from '../api'

const LABELS: Record<string, string> = {
  search_srd: 'Searched the SRD',
  get_srd_section: 'Read section',
  explore_srd_graph: 'Explored the graph',
  query_srd_graph: 'Queried the graph',
}

// Cypher arrives as several indented lines, which would push the trace to
// the height of the answer.  It is collapsed to one line and cut: the trace
// says what was looked up, and the rows it returned are the model's to read.
const CYPHER_CHARS = 80

function oneLine(cypher: string): string {
  const flat = cypher.replace(/\s+/g, ' ').trim()
  return flat.length > CYPHER_CHARS ? `${flat.slice(0, CYPHER_CHARS)}…` : flat
}

function summarise(call: ToolCall): string {
  const args = call.args as {
    query?: string; section_id?: string; entity_type?: string; cypher_query?: string
  }
  const subject = args.query ?? args.section_id
    ?? (args.cypher_query ? oneLine(args.cypher_query) : '')
  const filter = args.entity_type ? ` · ${args.entity_type}` : ''
  return `${LABELS[call.name] ?? call.name}${subject ? `: “${subject}”` : ''}${filter}`
}

export function ToolTrace({ tools }: { tools: ToolCall[] }) {
  const [open, setOpen] = useState(true)
  if (tools.length === 0) return null

  return (
    <div className="trace">
      <button className="trace-toggle" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} {tools.length} lookup{tools.length > 1 ? 's' : ''}
      </button>
      {open && (
        <ul>
          {tools.map((call) => (
            <li key={call.id} className={call.done ? 'done' : 'running'}>
              <span className="dot" />
              {summarise(call)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
