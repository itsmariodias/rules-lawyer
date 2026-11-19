/**
 * One row per tool call: a per-tool marker, what was looked at, and the
 * outcome.  Opening a row fetches that call's stored result.  Replayed
 * conversations start collapsed.
 */

import { useState } from 'react'
import { loadLookup, type ToolCall } from '../api'

const LABELS: Record<string, string> = {
  search_srd: 'Searched the SRD',
  get_srd_section: 'Read section',
  explore_srd_graph: 'Explored the graph',
  query_srd_graph: 'Queried the graph',
}

/** Text glyphs, so the four tools are distinguishable without colour. */
const MARKS: Record<string, string> = {
  search_srd: '≈',        // approximately: ranked, fuzzy, only the top few
  get_srd_section: '▤',   // a record, fetched whole and exactly
  explore_srd_graph: '⋈', // a join: the edges around a node
  query_srd_graph: '⌗',   // a query over structure, answering in rows
}

type Row = {
  subject: string
  /** Quoted and set in the body font; false for Cypher and ids. */
  prose: boolean
  outcome: string
  /** The untruncated argument, shown in the detail panel. */
  full?: string
}

function flatten(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/** Cypher as written; else the server's `subject`; else the quoted query; else the raw id. */
function describe(call: ToolCall): Row {
  const args = call.args as {
    query?: string; section_id?: string; cypher_query?: string
  }
  const summary = call.summary ?? ''

  if (args.cypher_query) {
    return { subject: flatten(args.cypher_query), prose: false,
             outcome: summary, full: args.cypher_query }
  }
  if (call.subject) {
    return { subject: call.subject, prose: true, outcome: summary }
  }
  if (args.query) {
    return { subject: `“${flatten(args.query)}”`, prose: true, outcome: summary }
  }
  return { subject: args.section_id ?? '', prose: false, outcome: summary }
}

function marker(call: ToolCall): string {
  if (!call.done) return '·'
  if (call.status === 'refused' || call.status === 'failed') return '✗'
  if (call.status === 'skipped') return '–'
  return MARKS[call.name] ?? '●'
}

function Line({ call, row }: { call: ToolCall; row: Row }) {
  const filter = (call.args as { entity_type?: string }).entity_type
  return (
    <>
      <span className="what">{LABELS[call.name] ?? call.name}</span>
      {row.subject && (
        <>
          <span className="sep" aria-hidden="true">-</span>
          <span className={row.prose ? 'asked prose' : 'asked'}>
            {row.subject}
          </span>
        </>
      )}
      {/* After the subject, not before the separator. */}
      {filter && <span className="filter">· {filter}</span>}
      <span className="outcome">{row.outcome}</span>
    </>
  )
}

type Fetched = { state: 'loading' | 'done' | 'failed'; text: string }

function Detail({ row, fetched }: { row: Row; fetched?: Fetched }) {
  return (
    <div className="detail">
      {/* Query above its result. */}
      {row.full && (
        <>
          <p className="detail-label">query</p>
          <pre><code>{row.full.trim()}</code></pre>
        </>
      )}
      <p className="detail-label">result</p>
      <pre className={fetched?.state === 'failed' ? 'detail-failed' : undefined}>
        <code>
          {fetched?.state === 'loading' ? 'Loading…' : fetched?.text ?? ''}
        </code>
      </pre>
    </div>
  )
}

export function ToolTrace(
  { tools, threadId, replayed = false }:
  { tools: ToolCall[]; threadId?: string | null; replayed?: boolean },
) {
  const [open, setOpen] = useState(!replayed)
  const [shown, setShown] = useState<string | null>(null)
  // Cached per trace; stored results never change.
  const [results, setResults] = useState<Record<string, Fetched>>({})

  const reveal = async (call: ToolCall) => {
    if (shown === call.id) {
      setShown(null)
      return
    }
    setShown(call.id)
    if (!threadId || results[call.id]) return
    setResults((current) => ({
      ...current, [call.id]: { state: 'loading', text: '' },
    }))
    try {
      const found = await loadLookup(threadId, call.id)
      setResults((current) => ({
        ...current,
        [call.id]: {
          state: 'done',
          text: found.truncated
            ? `${found.content}\n\n… cut here; the rest is longer than this panel.`
            : found.content,
        },
      }))
    } catch {
      setResults((current) => ({
        ...current,
        [call.id]: {
          state: 'failed', text: 'That result could not be read back.',
        },
      }))
    }
  }

  if (tools.length === 0) return null

  return (
    <div className="trace">
      <button className="trace-toggle" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} {tools.length} lookup
        {tools.length > 1 ? 's' : ''}
      </button>
      {open && (
        <ul>
          {tools.map((call) => {
            const row = describe(call)
            const expanded = shown === call.id
            const openable = call.done && Boolean(threadId)
            return (
              <li
                key={call.id}
                className={[
                  call.done ? 'done' : 'running',
                  call.status ? `is-${call.status}` : '',
                ].filter(Boolean).join(' ')}
              >
                <span className="mark" aria-hidden="true">{marker(call)}</span>
                {openable ? (
                  <button
                    className="line"
                    aria-expanded={expanded}
                    onClick={() => reveal(call)}
                  >
                    <Line call={call} row={row} />
                  </button>
                ) : (
                  <span className="line"><Line call={call} row={row} /></span>
                )}
                {expanded && <Detail row={row} fetched={results[call.id]} />}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
