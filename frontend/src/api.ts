/**
 * The browser's half of the contract in `api.py`.
 *
 * One streaming call and three plain ones.  The event union here mirrors the
 * dicts `chat/service.py` yields, so adding an event type is a change in two
 * files and nowhere else.
 */

export type Citation = {
  section_id: string
  heading: string | null
  entity_type: string | null
  page: number | null
  labels: string[]
}

/** How a finished tool call went, for the trace to draw. */
export type ToolStatus = 'ok' | 'empty' | 'refused' | 'failed'

export type ToolCall = {
  id: string
  name: string
  args: Record<string, unknown>
  done: boolean
  /** These arrive with tool_end, so all three are absent while it runs. */
  status?: ToolStatus
  summary?: string
  /**
   * What the call looked at, where only the server can say. A dotted id
   * means nothing to a reader, and the graph is the only thing that knows
   * `11.2.70` is Frightened.
   */
  subject?: string
}

export type ChatEvent =
  | { type: 'start'; thread_id: string }
  | { type: 'token'; text: string }
  | { type: 'tool_start'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_end'; id: string; name: string; result_chars: number;
      status?: ToolStatus; summary?: string; subject?: string }
  | { type: 'citations'; citations: Citation[] }
  /** The model could not answer, and nothing answers in its place. */
  | { type: 'error'; message: string }
  | { type: 'done'; thread_id: string }

export type Message = {
  role: 'user' | 'assistant'
  content: string
  /**
   * Read back from the server rather than watched as it happened, which is
   * what decides whether its trace opens on arrival.
   */
  replayed?: boolean
  /**
   * When the turn was written, as an ISO string. The server takes it from
   * the checkpoint that stored the message, so a reopened conversation is
   * dated by when it happened rather than by when it was read.
   */
  at?: string
  /** How long the answer took, in milliseconds. Live turns only. */
  ms?: number
  citations?: Citation[]
  tools?: ToolCall[]
  error?: string
}

export type Thread = {
  thread_id: string
  title: string
  updated_at: string | null
  messages: number
  /** Pinned threads sort above the rest; the server decides the order. */
  pinned: boolean
}

export type Box = {
  page: number
  x0: number
  y0: number
  x1: number
  y1: number
}

export type SourceExcerpt = {
  section_id: string
  heading: string | null
  entity_type: string | null
  page: number | null
  labels?: string[]
  text: string
  highlight: { start: number; end: number } | null
  /** Rectangles of the cited lines, in PDF points, origin top-left. */
  boxes: Box[]
  /** Every page those rectangles fall on, ascending. */
  pages: number[]
  parent: { id: string; heading: string } | null
  children: { id: string; heading: string }[]
}

/**
 * One node of the graph, as the explorer draws it.
 *
 * `uid` is Neo4j's own element id, not the section id: the interesting
 * neighbours are not all sections — an ability is keyed on `key`, a damage
 * type on `name` — so the only identifier every node has is the node.
 * `section_id` is present on the ones that *are* a section, and is what
 * decides whether this node can be opened on the page.
 */
export type GraphNode = {
  uid: string
  name: string | null
  labels: string[]
  entity_type: string | null
  section_id: string | null
  page: number | null
  /** The opening of what this node says, markdown stripped. */
  summary: string | null
  /**
   * What a node with no prose at all carries instead — a weapon is a table
   * row with a cost and a die and not one sentence in the book.
   */
  facts: { name: string; value: string }[]
  /** Edges on this node in the whole graph, not in what was returned. */
  degree: number
  /** Hops from the node the view was opened on. */
  depth: number
}

export type GraphEdge = {
  uid: string
  type: string
  source: string
  target: string
}

/** A fan-out the server sampled rather than returned whole. */
export type GraphTruncation = {
  uid: string
  type: string
  direction: 'in' | 'out'
  total: number
  shown: number
}

export type Neighbourhood = {
  root: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  truncated: GraphTruncation[]
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json() as Promise<T>
}

/**
 * Whether the graph can answer anything, as three states rather than two.
 *
 * A reachable but empty database is its own failure: every question comes
 * back with nothing, and "connected" would be a true sentence that misleads.
 * `/graph/health` counts what is in Neo4j rather than remembering a load, so
 * both answers come from the one request. It never throws: an unreachable
 * database is a status, not an error the caller has to catch.
 */
export type GraphStatus = 'checking' | 'connected' | 'empty' | 'unreachable'

export async function graphStatus(): Promise<GraphStatus> {
  try {
    const health = await getJSON<{ nodes: Record<string, number> }>(
      '/graph/health')
    const nodes = Object.values(health.nodes ?? {})
      .reduce((total, count) => total + count, 0)
    return nodes > 0 ? 'connected' : 'empty'
  } catch {
    return 'unreachable'
  }
}

/**
 * What one lookup returned, fetched only when a reader opens it.
 *
 * Not part of the conversation: one turn can store a hundred kilobytes of
 * table across twenty lookups, almost none of which anyone opens, so the
 * trace carries counts and this fetches the rest on demand.
 */
export type Lookup = {
  id: string
  name: string
  content: string
  truncated: boolean
}

export const loadLookup = (threadId: string, callId: string) =>
  getJSON<Lookup>(
    `/chat/threads/${threadId}/lookups/${encodeURIComponent(callId)}`)

export const listThreads = () =>
  getJSON<{ threads: Thread[] }>('/chat/threads').then((r) => r.threads)

export const loadThread = (id: string) =>
  getJSON<{ messages: Message[] }>(`/chat/threads/${id}`).then((r) => r.messages)

/** Pin or unpin one conversation, which only moves it in the list. */
export async function pinThread(id: string, pinned: boolean): Promise<void> {
  const response = await fetch(`/api/chat/threads/${id}/pin`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pinned }),
  })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
}

/**
 * Delete one conversation and everything checkpointed under it.
 *
 * The checkpointer is the whole store, so there is nothing left afterwards
 * and nothing to undo it with.
 */
export async function deleteThread(id: string): Promise<void> {
  const response = await fetch(`/api/chat/threads/${id}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
}

export const loadSource = (sectionId: string, context = 0) =>
  getJSON<SourceExcerpt>(`/source/${sectionId}?context=${context}`)

/**
 * The graph around one node.
 *
 * A citation names a section, an expansion names a node it was already
 * shown, and the server takes exactly one of the two.  `fan` is how many
 * neighbours it may return per relationship type per direction; it is what
 * asking a hub for *more* raises, since asking again for the same number
 * would return the same sample.
 */
export const loadNeighbourhood = (
  seed: { section: string } | { node: string },
  depth: number,
  fan?: number,
) => {
  const query = new URLSearchParams({ ...seed, depth: String(depth) })
  if (fan !== undefined) query.set('fan', String(fan))
  return getJSON<Neighbourhood>(`/neighbourhood?${query}`)
}

/**
 * Send one message and invoke `onEvent` for each server-sent event.
 *
 * `fetch` rather than `EventSource`, because the request is a POST with a
 * body and `EventSource` can only GET.  That means framing the stream here:
 * SSE separates events with a blank line, and a chunk boundary can land
 * anywhere, so the tail of a chunk is held back until its blank line arrives.
 */
export async function streamChat(
  message: string,
  threadId: string | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`${response.status} ${response.statusText}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? ''
    for (const frame of frames) {
      const line = frame.split('\n').find((l) => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)) as ChatEvent)
    }
  }
}
