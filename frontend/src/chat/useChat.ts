/**
 * Conversation state for the open thread.  History lives on the server; the
 * streaming assistant message is always the last element of `messages`.  The
 * open thread is also the address bar's path (`route.ts`), so a reload, a
 * link or Back opens it.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteThread, listThreads, loadThread, pinThread, retryChat, streamChat,
  type ChatEvent, type Message, type Thread,
} from '../api'
import { showThread, threadOf } from './route'

export function useChat() {
  const [messages, setMessages] = useState<Message[]>([])
  const [threads, setThreads] = useState<Thread[]>([])
  const [threadId, setThreadId] = useState<string | null>(null)
  const [streaming, setStreaming] = useState(false)
  // True from arriving on a thread's path until it has loaded or failed, so
  // the screen does not flash the new chat first.
  const [arriving, setArriving] = useState(
    () => threadOf(window.location.pathname) !== null)
  const abort = useRef<AbortController | null>(null)

  const refreshThreads = useCallback(() => {
    listThreads().then(setThreads).catch(() => setThreads([]))
  }, [])

  useEffect(refreshThreads, [refreshThreads])

  const patchLast = (change: (message: Message) => Message) =>
    setMessages((current) =>
      current.map((message, index) =>
        index === current.length - 1 ? change(message) : message))

  const apply = (event: ChatEvent) => {
    switch (event.type) {
      case 'start':
        setThreadId(event.thread_id)
        // The new chat becomes this thread, rather than leaving an empty
        // page for Back to return to.
        showThread(event.thread_id, 'replace')
        // The server lists a thread only once its turn is stored; until then
        // it is listed here, untitled.
        setThreads((current) =>
          current.some((thread) => thread.thread_id === event.thread_id)
            ? current
            : [{ thread_id: event.thread_id, title: '', pinned: false,
                 updated_at: new Date().toISOString(), messages: 1 },
               ...current])
        break
      case 'title':
        setThreads((current) => current.map((thread) =>
          thread.thread_id === event.thread_id
            ? { ...thread, title: event.title }
            : thread))
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
      case 'usage': {
        const { type: _, ...usage } = event
        patchLast((m) => ({ ...m, usage }))
        break
      }
      case 'citations':
        patchLast((m) => ({ ...m, citations: event.citations }))
        break
      case 'error':
        patchLast((m) => ({ ...m, error: event.message }))
        break
    }
  }

  /** Stream a turn (send or retry) into the trailing assistant message. */
  const run = useCallback(async (
    ask: (onEvent: (event: ChatEvent) => void, signal: AbortSignal) => Promise<void>,
  ) => {
    const started = Date.now()
    setStreaming(true)
    const controller = new AbortController()
    abort.current = controller
    try {
      await ask(apply, controller.signal)
    } catch (error) {
      const stopped = controller.signal.aborted
      patchLast((m) => stopped
        ? { ...m, stopped: true }
        : { ...m, error: String(error) })
    } finally {
      // Client-side, so it is the wait the reader actually saw.
      patchLast((m) => ({ ...m, ms: Date.now() - started }))
      setStreaming(false)
      abort.current = null
      refreshThreads()
    }
  }, [refreshThreads])

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

  /** Drop everything after the last question and ask it again. */
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

  // Refetched rather than resorted: the server owns the order.
  const pin = useCallback(async (id: string, pinned: boolean) => {
    await pinThread(id, pinned)
    refreshThreads()
  }, [refreshThreads])

  /** Empty the screen for a new chat, leaving the address bar alone. */
  const clear = useCallback(() => {
    abort.current?.abort()
    setThreadId(null)
    setMessages([])
  }, [])

  /** Delete a thread, clearing the view if it was the open one. */
  const forget = useCallback(async (id: string) => {
    await deleteThread(id)
    if (id === threadId) {
      clear()
      showThread(null, 'replace')
    }
    refreshThreads()
  }, [threadId, clear, refreshThreads])

  /**
   * Show a stored thread, leaving the address bar alone.  The id changes
   * only once its messages arrive, so a failed load leaves the next question
   * in the thread on screen; the list is refetched, since the usual cause is
   * a thread deleted elsewhere.
   *
   * Returns whether it loaded.
   */
  const load = useCallback(async (id: string) => {
    abort.current?.abort()
    let loaded: Message[]
    try {
      loaded = await loadThread(id)
    } catch {
      refreshThreads()
      return false
    }
    setThreadId(id)
    setMessages(loaded.map((message) => ({ ...message, replayed: true })))
    return true
  }, [refreshThreads])

  /** Show a stored thread at its own path. */
  const open = useCallback(async (id: string) => {
    if (await load(id)) showThread(id, 'push')
  }, [load])

  /** Start a new chat at `/`. */
  const reset = useCallback(() => {
    clear()
    showThread(null, 'push')
  }, [clear])

  // Show what the path names, on arrival and on Back or Forward.  A path
  // naming a thread that will not load is replaced, so it is not kept.
  useEffect(() => {
    const follow = async () => {
      const id = threadOf(window.location.pathname)
      if (id === null) clear()
      else if (!(await load(id))) {
        clear()
        showThread(null, 'replace')
      }
      setArriving(false)
    }
    void follow()
    window.addEventListener('popstate', follow)
    return () => window.removeEventListener('popstate', follow)
  }, [load, clear])

  return { messages, threads, threadId, streaming, arriving, send, retry,
           stop, open, reset, forget, pin }
}
