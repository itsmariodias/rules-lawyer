/**
 * What the agent looked up, shown while it looks it up.
 *
 * A graph RAG answer is only trustworthy if you can see the retrieval, and
 * during a slow first token this is the only sign the thing is alive.
 *
 * One line per call, and that line has to carry three things a muted dot and
 * a label did not. *Which kind* of lookup it was: a ranked fuzzy search, an
 * exact query over the whole graph and a fetch of one section by id are
 * different operations, and drawing them identically makes an agent that is
 * reasoning look like one repeating itself. *How it went*: a refused query
 * used to draw the same grey dot as a perfect one. And *what came back*,
 * which sits at the right-hand end of the same line.
 *
 * Opening a row shows what it actually returned, which is the retrieval
 * inspector the whole project implies. It costs a request rather than a
 * larger conversation: one turn can store a hundred kilobytes of table
 * across twenty lookups, almost none of which anyone opens.
 *
 * A conversation being reopened arrives with its trace folded away. Watching
 * the retrieval happen is the point of it during a turn; coming back to a
 * conversation you want the answer, with the working still a click away.
 */

import { useCallback, useState } from 'react'
import { loadLookup } from '../api'
import type { ToolCall } from '../api'

const LABELS: Record<string, string> = {
  search_srd: 'Searched the SRD',
  get_srd_section: 'Read section',
  explore_srd_graph: 'Explored the graph',
  query_srd_graph: 'Queried the graph',
}

/**
 * Markers, chosen to separate the operations rather than decorate them.
 *
 * Text rather than shapes, so the four stay distinguishable without relying
 * on colour.
 */
const MARKS: Record<string, string> = {
  search_srd: '≈',        // approximately: ranked, fuzzy, only the top few
  get_srd_section: '▤',   // a record, fetched whole and exactly
  explore_srd_graph: '⋈', // a join: the edges around a node
  query_srd_graph: '⌗',   // a query over structure, answering in rows
}

type Row = {
  /** What was asked for, to the right of the label. */
  subject: string
  /** Prose is quoted and set in the body font; Cypher and ids are not. */
  prose: boolean
  /** What came back, at the right-hand end of the line. */
  outcome: string
  /** The argument in full, where the line shows only as much as fits. */
  full?: string
}

function flatten(text: string): string {
  return text.replace(/\s+/g, ' ').trim()
}

/**
 * One call, as the row reads it.
 *
 * Each tool puts something different in front of a reader. A search is the
 * words the model chose, so it is quoted. A section read and a graph walk
 * are reached by a dotted id, which names nothing to anyone, so the server
 * sends what it found there instead.
 */
function describe(call: ToolCall): Row {
  const args = call.args as {
    query?: string; section_id?: string; cypher_query?: string
  }
  const summary = call.summary ?? ''

  // Cypher is its own argument and worth reading as written, so it is never
  // replaced by anything the server would rather say.
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
  // Until the call finishes, the id is all there is to show.
  return { subject: args.section_id ?? '', prose: false, outcome: summary }
}

function marker(call: ToolCall): string {
  if (!call.done) return '·'
  // A call that did not do what was asked says so in the marker, whatever
  // tool it was: the kind of lookup stops being the interesting fact.
  if (call.status === 'refused' || call.status === 'failed') return '✗'
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
      {/* Beside what it narrowed, rather than before the separator, where
          two dividers in a row read as punctuation for its own sake. */}
      {filter && <span className="filter">· {filter}</span>}
      <span className="outcome">{row.outcome}</span>
    </>
  )
}

/** The result of one lookup, once someone has asked to see it. */
type Fetched = { state: 'loading' | 'done' | 'failed'; text: string }

function Detail({ row, fetched }: { row: Row; fetched?: Fetched }) {
  return (
    <div className="detail">
      {/* The query leads, because a result only means something beside the
          question that produced it. */}
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
  // Kept for the life of the trace: reopening a row a reader just closed
  // should not go back to the server for something that cannot have changed.
  const [results, setResults] = useState<Record<string, Fetched>>({})

  const reveal = useCallback(async (call: ToolCall) => {
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
      // The lookup happened; only reading it back failed, and saying so
      // beats an empty panel that reads as "it returned nothing".
      setResults((current) => ({
        ...current,
        [call.id]: {
          state: 'failed', text: 'That result could not be read back.',
        },
      }))
    }
  }, [shown, threadId, results])

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
            // Nothing to open until the call has returned something.
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
