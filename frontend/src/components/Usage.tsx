/**
 * What an answer cost in tokens, in the row that says when it was.
 *
 * One number in the row, the total, because that is what counts against a
 * quota. How it divides is on hover: an agentic turn re-reads the system
 * prompt and every result on each call, so the total is mostly reading, and
 * saying that out loud on every answer would be noise.
 */

import type { Usage as Counts } from '../api'

const grouped = (n: number) => n.toLocaleString('en-US')

/** `18240` → `18,240 tokens`; one is a token. */
export function formatTokens(n: number): string {
  return `${grouped(n)} ${n === 1 ? 'token' : 'tokens'}`
}

export function Usage({ usage }: { usage: Counts }) {
  const calls = `${usage.calls} model ${usage.calls === 1 ? 'call' : 'calls'}`
  return (
    <span className="usage"
          title={`${grouped(usage.input)} in · ${grouped(usage.output)} out · ${calls}`}>
      {formatTokens(usage.total)}
    </span>
  )
}
