/**
 * The open thread in the address bar: `/chat/<id>` for a stored thread, `/`
 * for a new chat.
 */

const PREFIX = '/chat/'

/** The path that shows this thread, or a new chat for null. */
export function threadPath(id: string | null): string {
  return id === null ? '/' : PREFIX + encodeURIComponent(id)
}

/** The thread a path names, or null if it names none. */
export function threadOf(pathname: string): string | null {
  if (!pathname.startsWith(PREFIX)) return null
  const id = decodeURIComponent(pathname.slice(PREFIX.length))
  return id && !id.includes('/') ? id : null
}

/**
 * Point the address bar at a thread.  A push adds a history entry, so Back
 * returns to the thread before; a replace swaps the current one.  Nothing
 * changes if the bar already shows it.
 */
export function showThread(id: string | null, how: 'push' | 'replace') {
  const path = threadPath(id)
  if (window.location.pathname === path) return
  if (how === 'push') window.history.pushState(null, '', path)
  else window.history.replaceState(null, '', path)
}
