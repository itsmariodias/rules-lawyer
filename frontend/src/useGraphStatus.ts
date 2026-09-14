/**
 * Whether the graph behind the answers is up, asked once and then let be.
 *
 * It retries only while the answer is bad: a database that comes up after
 * the app did would otherwise be labelled unreachable for the rest of the
 * session, and a label that is wrong forever is worse than no label. Once
 * it is connected there is nothing to watch for, so the timer stops.
 */

import { useEffect, useState } from 'react'
import { graphStatus, type GraphStatus } from './api'

export const RETRY_MS = 15_000

export function useGraphStatus(): GraphStatus {
  const [status, setStatus] = useState<GraphStatus>('checking')
  // The flag rather than the status itself: depending on the status would
  // tear the timer down and ask again on the way from checking to
  // unreachable, which is the same bad news twice.
  const connected = status === 'connected'

  useEffect(() => {
    if (connected) return

    let live = true
    const ask = () => void graphStatus().then((s) => { if (live) setStatus(s) })
    ask()
    const timer = setInterval(ask, RETRY_MS)
    return () => { live = false; clearInterval(timer) }
  }, [connected])

  return status
}
