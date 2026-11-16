/** Graph availability, polled every `RETRY_MS` until it is `connected`. */

import { useEffect, useState } from 'react'
import { graphStatus, type GraphStatus } from '../api'

export const RETRY_MS = 15_000

export function useGraphStatus(): GraphStatus {
  const [status, setStatus] = useState<GraphStatus>('checking')
  // Depend on the boolean so checking -> unreachable does not restart polling.
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
