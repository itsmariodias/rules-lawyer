/** An answer's total token count, with the in/out/calls split on hover. */

import type { Usage as Counts } from '../api'

const grouped = (n: number) => n.toLocaleString('en-US')

/** `18240` -> `18,240 tokens`. */
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
