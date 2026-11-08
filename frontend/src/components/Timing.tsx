/** `Clock` dates a finished turn; `Elapsed` counts up while one runs. */

import { useEffect, useState } from 'react'

/** `4.2s` under ten seconds, `42s` under a minute, then `1m 05s`. */
export function formatDuration(ms: number): string {
  const seconds = ms / 1000
  if (seconds < 10) return `${seconds.toFixed(1)}s`
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${String(Math.round(seconds % 60)).padStart(2, '0')}s`
}

function sameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear()
    && a.getMonth() === b.getMonth()
    && a.getDate() === b.getDate()
}

/** Time only for today; "Yesterday, <time>"; else date and time, year if not this one. */
export function formatMoment(when: Date, now: Date = new Date()): string {
  const time = when.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (sameDay(when, now)) return time

  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (sameDay(when, yesterday)) return `Yesterday, ${time}`

  const date = when.toLocaleDateString([], {
    day: 'numeric',
    month: 'short',
    ...(when.getFullYear() === now.getFullYear() ? {} : { year: 'numeric' }),
  })
  return `${date}, ${time}`
}

export function Clock({ at, title }: { at?: string; title?: string }) {
  if (!at) return null
  const when = new Date(at)
  if (Number.isNaN(when.getTime())) return null
  return (
    <time className="stamp" dateTime={at}
          title={title ?? when.toLocaleString()}>
      {formatMoment(when)}
    </time>
  )
}

/** Time since `since`, re-rendered every 100ms so the tenths move. */
export function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(tick)
  }, [since])

  return (
    <span className="elapsed" aria-hidden="true">
      {formatDuration(Math.max(0, now - since))}
    </span>
  )
}
