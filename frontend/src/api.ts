/**
 * Client for the backend API.  `ChatEvent` mirrors the dicts
 * `chat/turn.py` yields; keep the two in step.
 */

export type Citation = {
  section_id: string
  heading: string | null
  entity_type: string | null
  page: number | null
  labels: string[]
}

export type ToolStatus = 'ok' | 'empty' | 'refused' | 'failed'

export type ToolCall = {
  id: string
  name: string
  args: Record<string, unknown>
  done: boolean
  /** Set by `tool_end`; absent while the call runs. */
  status?: ToolStatus
  summary?: string
  /** The heading a dotted-id argument names, resolved by the server. */
  subject?: string
}

export type ChatEvent =
  | { type: 'start'; thread_id: string }
  /** A new thread's title (the model's, or the cut question) once known. */
  | { type: 'title'; thread_id: string; title: string }
  | { type: 'token'; text: string }
  | { type: 'tool_start'; id: string; name: string; args: Record<string, unknown> }
  | { type: 'tool_end'; id: string; name: string; result_chars: number;
      status?: ToolStatus; summary?: string; subject?: string }
  | ({ type: 'usage' } & Usage)
  | { type: 'citations'; citations: Citation[] }
  | { type: 'error'; message: string }
  | { type: 'done'; thread_id: string }

/** Token usage summed over every model call in one turn. */
export type Usage = {
  input: number
  output: number
  total: number
  calls: number
}

export type Message = {
  role: 'user' | 'assistant'
  content: string
  /** Loaded from history rather than streamed; its trace starts closed. */
  replayed?: boolean
  /** ISO timestamp of the checkpoint that stored the message. */
  at?: string
  /** Send-to-done duration in ms; live turns only. */
  ms?: number
  /** The reader stopped the turn before it finished; live turns only. */
  stopped?: boolean
  /** Null when the stored turn carries no counts. */
  usage?: Usage | null
  citations?: Citation[]
  tools?: ToolCall[]
  error?: string
}

export type Thread = {
  thread_id: string
  /** Empty while a new thread waits for its first turn to be stored. */
  title: string
  updated_at: string | null
  messages: number
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
  /** Pages the boxes fall on, ascending. */
  pages: number[]
  /** From the top-level section down to the parent; empty at the top. */
  ancestors: { id: string; heading: string }[]
  parent: { id: string; heading: string } | null
  children: { id: string; heading: string }[]
}

/**
 * A graph node.  `uid` is Neo4j's element id, since derived nodes have no
 * section id; `section_id` is set only on nodes that are sections.
 */
export type GraphNode = {
  uid: string
  name: string | null
  labels: string[]
  entity_type: string | null
  section_id: string | null
  page: number | null
  /** Plain-text opening of the node's prose. */
  summary: string | null
  /** Properties to show when there is no summary. */
  facts: { name: string; value: string }[]
  /** Edge count in the whole graph, not just in this response. */
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

/** A (node, type, direction) group the fan cap cut. */
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

/**
 * The error for a refused request: the server's `detail` when it sent one
 * (FastAPI's shape, and where the chat explains a missing key), else the
 * status line.
 */
async function failure(response: Response): Promise<Error> {
  try {
    const body = await response.json() as { detail?: unknown } | null
    if (typeof body?.detail === 'string') return new Error(body.detail)
  } catch {
    // No JSON body, as from a proxy's error page.
  }
  return new Error(`${response.status} ${response.statusText}`)
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`)
  if (!response.ok) throw await failure(response)
  return response.json() as Promise<T>
}

export type GraphStatus = 'checking' | 'connected' | 'empty' | 'unreachable'

/** Probe `/graph/health`.  Never throws; `empty` means reachable with no nodes. */
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

/** One tool call's stored result, fetched when its trace row is opened. */
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

export async function pinThread(id: string, pinned: boolean): Promise<void> {
  const response = await fetch(`/api/chat/threads/${id}/pin`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pinned }),
  })
  if (!response.ok) throw await failure(response)
}

export async function deleteThread(id: string): Promise<void> {
  const response = await fetch(`/api/chat/threads/${id}`, { method: 'DELETE' })
  if (!response.ok) throw await failure(response)
}

export const loadSource = (sectionId: string, context = 0) =>
  getJSON<SourceExcerpt>(`/source/${sectionId}?context=${context}`)

/**
 * The graph around a section or a node, or with a `null` seed around the
 * book, a node the server joins to every top-level section.  `fan` caps
 * neighbours per relationship type and direction; the server's sample is
 * deterministic, so asking for more means raising it.
 */
export const loadNeighbourhood = (
  seed: { section: string } | { node: string } | null,
  depth: number,
  fan?: number,
) => {
  const query = new URLSearchParams({ ...seed, depth: String(depth) })
  if (fan !== undefined) query.set('fan', String(fan))
  return getJSON<Neighbourhood>(`/neighbourhood?${query}`)
}

/**
 * POST and parse the SSE response, calling `onEvent` per event.
 *
 * `fetch`, not `EventSource`, which cannot POST.  A chunk can end mid-frame,
 * so the text after the last blank line is held for the next chunk.
 */
async function stream(
  path: string,
  body: unknown,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) throw await failure(response)

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

/** Send a message; a null `threadId` starts a new thread. */
export const streamChat = (
  message: string,
  threadId: string | null,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
) => stream('/chat', { message, thread_id: threadId }, onEvent, signal)

/** Re-ask a thread's last question; the server replaces its answer. */
export const retryChat = (
  threadId: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
) => stream(`/chat/threads/${threadId}/retry`, null, onEvent, signal)
