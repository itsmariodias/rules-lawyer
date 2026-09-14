/**
 * When a turn happened, and how long it is taking.
 *
 * Two pieces of the same concern, which is why they share a file. `Clock`
 * dates a finished turn from the moment the server stored it; `Elapsed`
 * counts up while one is still running.
 *
 * The counter matters more than it looks. An agentic turn makes a round
 * trip before it says anything, and on a hard question it makes eight, so
 * the wait before the first token is long enough to read as a hang. A
 * number that moves is the difference between waiting and wondering.
 */

import { useEffect, useState } from 'react'

/**
 * A duration a person can read at a glance.
 *
 * Tenths below ten seconds, because that is where the difference between
 * 1.2s and 4.8s is the interesting part; whole seconds above it, where a
 * tenth is noise on a number that is already the headline.
 */
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

/**
 * When a turn happened, said as briefly as it can be without ambiguity.
 *
 * The time alone is enough for today and wrong for anything else: a
 * conversation from three days ago reading "11:15 PM" invites the reader to
 * take it for this evening. So the date appears exactly when the time stops
 * being sufficient, and the year only once it is not this one.
 */
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

/** When a turn was written, in the reader's own locale. */
export function Clock({ at, title }: { at?: string; title?: string }) {
  if (!at) return null
  const when = new Date(at)
  if (Number.isNaN(when.getTime())) return null
  return (
    <time className="stamp" dateTime={at}
          // The exact moment, seconds and all, for anyone who wants it.
          title={title ?? when.toLocaleString()}>
      {formatMoment(when)}
    </time>
  )
}

/**
 * How long the turn has been running, counted from when it was sent.
 *
 * Ticks ten times a second so the tenths actually move; a number that
 * updates once a second reads as stalled between beats, which is the one
 * impression this exists to prevent.
 */
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
