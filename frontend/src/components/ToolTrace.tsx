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
}

function summarise(call: ToolCall): string {
  const args = call.args as { query?: string; section_id?: string; entity_type?: string }
  const subject = args.query ?? args.section_id ?? ''
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
