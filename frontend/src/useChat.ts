/**
 * Conversation state for one thread.
 *
 * The server owns the history; this owns only what is on screen, which is
 * why switching threads is a fetch rather than a cache lookup. The streaming
 * assistant message is always the last element of `messages` and is mutated
 * in place as tokens arrive.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteThread, listThreads, loadThread, pinThread, retryChat, streamChat,
  type ChatEvent, type Message, type Thread,
} from './api'

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [threads, setThreads] = useState<Thread[]>([])
  const [threadId, setThreadId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  const abort = useRef<AbortController | null>(null)

  const refreshThreads = useCallback(() => {
    listThreads().then(setThreads).catch(() => setThreads([]))
  }, [])

  useEffect(refreshThreads, [refreshThreads])

  /** Replace the in-flight assistant message, which is always the last one. */
  const patchLast = (change: (message: Message) => Message) =>
    setMessages((current) =>
      current.map((message, index) =>
        index === current.length - 1 ? change(message) : message))

  const apply = (event: ChatEvent) => {
    switch (event.type) {
      case 'start':
        setThreadId(event.thread_id)
        break
      case 'token':
        patchLast((m) => ({ ...m, content: m.content + event.text }))
        break
      case 'tool_start':
        patchLast((m) => ({
          ...m,
          tools: [...(m.tools ?? []),
            { id: event.id, name: event.name, args: event.args, done: false }],
        }))
        break
      case 'tool_end':
        patchLast((m) => ({
          ...m,
          tools: (m.tools ?? []).map((t) =>
            t.id === event.id
              ? { ...t, done: true, status: event.status,
                  summary: event.summary, subject: event.subject }
              : t),
        }))
        break
      case 'citations':
        patchLast((m) => ({ ...m, citations: event.citations }))
        break
      case 'error':
        patchLast((m) => ({ ...m, error: event.message }))
        break
    }
  }

  /**
   * Stream one turn into the assistant message already at the end.
   *
   * It takes the call to make rather than the question, because asking and
   * asking again differ only in that: the timing, the abort, the error and
   * the refreshed sidebar are the same either way.
   */
  const run = useCallback(async (
    ask: (onEvent: (event: ChatEvent) => void, signal: AbortSignal) => Promise<void>,
  ) => {
    const isFirst = threadId === null
    const started = Date.now()
    setStreaming(true)
    abort.current = new AbortController()
    try {
      await ask(apply, abort.current.signal)
    } catch (error) {
      if (!abort.current.signal.aborted) {
        patchLast((m) => ({ ...m, error: String(error) }))
      }
    } finally {
      // Measured here rather than from the timestamps, which are the
      // server's and are written a step at a time: what a reader watched is
      // the wait from pressing send to the stream ending.
      patchLast((m) => ({ ...m, ms: Date.now() - started }))
      setStreaming(false)
      abort.current = null
      // The sidebar only changes when a thread is created or its preview
      // moves to the top, so it is refreshed after a turn, not during one.
      refreshThreads()
      if (isFirst) refreshThreads()
    }
  }, [threadId, refreshThreads])

  const send = useCallback(async (text: string) => {
    if (streaming || !text.trim()) return
    const at = new Date().toISOString()
    setMessages((current) => [
      ...current,
      { role: 'user', content: text, at },
      { role: 'assistant', content: '', at },
    ])
    await run((onEvent, signal) => streamChat(text, threadId, onEvent, signal))
  }, [streaming, threadId, run])

  /**
   * Ask the last question again, in place of the answer it got.
   *
   * The old answer is dropped here and on the server both: it rewinds the
   * checkpoint rather than appending, so a conversation reopened later holds
   * one question where the reader asked one. The question itself is not
   * re-sent: the server reads what was asked out of the checkpoint, which
   * is what keeps the two halves from disagreeing about what is being
   * retried.
   */
  const retry = useCallback(async () => {
    if (streaming || threadId === null) return
    const asked = messages.map((m) => m.role).lastIndexOf('user')
    if (asked === -1) return
    setMessages((current) => [
      ...current.slice(0, asked + 1),
      { role: 'assistant', content: '', at: new Date().toISOString() },
    ])
    await run((onEvent, signal) => retryChat(threadId, onEvent, signal))
  }, [streaming, threadId, messages, run])

  const stop = useCallback(() => abort.current?.abort(), [])

  /**
   * Delete a conversation.
   *
   * The list is refreshed from the server rather than filtered here, so
   * what is on screen is what is stored. Deleting the thread being read
   * clears it too — leaving its turns up with nothing behind them would
   * invite a reply into a thread that no longer exists.
   */
  /**
   * Pin or unpin a conversation.
   *
   * The order is the server's, so the list is refetched rather than
   * resorted here — there is one answer to where a thread sits and it is
   * not the browser's.
   */
  const pin = useCallback(async (id: string, pinned: boolean) => {
    await pinThread(id, pinned)
    refreshThreads()
  }, [refreshThreads])

  const forget = useCallback(async (id: string) => {
    await deleteThread(id)
    if (id === threadId) {
      abort.current?.abort()
      setThreadId(null)
      setMessages([])
    }
    refreshThreads()
  }, [threadId, refreshThreads])

  const open = useCallback(async (id: string) => {
    abort.current?.abort()
    setThreadId(id)
    // Marked on the way in, because it is the one thing the server cannot
    // say: the same turn is live when it is watched and replayed when it is
    // reopened, and only the reader knows which.
    setMessages((await loadThread(id)).map(
      (message) => ({ ...message, replayed: true })))
  }, [])

  const reset = useCallback(() => {
    abort.current?.abort()
    setThreadId(null)
    setMessages([])
  }, [])

  return { messages, threads, threadId, streaming, send, retry,
           stop, open, reset, forget, pin }
}
