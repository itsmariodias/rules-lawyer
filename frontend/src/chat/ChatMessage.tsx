/**
 * One message in the conversation.  A question shows its time; an answer
 * shows its lookups, its markdown (or "Thinking" while nothing has arrived),
 * any error, "Stopped" if the reader stopped it, its citations, and a row of
 * time, cost, copy and retry.
 */

import { memo, useEffect, useState } from 'react'
import type { Citation, Message } from '../api'
import { CopyIcon, RetryIcon, TickIcon } from '../shared/icons'
import { Markdown } from './Markdown'
import { Clock, Elapsed, formatDuration } from './Timing'
import { ToolTrace } from './ToolTrace'
import { Usage } from './Usage'

type Props = {
  message: Message
  /** The turn is still streaming into this message. */
  running: boolean
  threadId: string | null
  /** Offered only when given: the last question and answer of a finished turn. */
  onRetry?: () => void
  onCite: (sectionId: string) => void
}

/**
 * Memoised: every streamed token re-renders the conversation, and without
 * this each earlier answer re-parses its markdown (about 70ms a token over
 * 20 turns, measured in jsdom).  Its props must stay stable to keep that.
 */
export const ChatMessage = memo(function ChatMessage(
  { message, running, threadId, onRetry, onCite }: Props,
) {
  const since = running && message.at ? new Date(message.at).getTime() : null

  if (message.role === 'user') {
    return (
      <article className="message user">
        <p>{message.content}</p>
        {/* Not a <p>: every <p> in a user message is styled as the bubble.
            Retry here covers reopened failed turns, which have no answer to
            hang it on. */}
        <div className="timing">
          <Clock at={message.at} />
          {onRetry && <Retry onRetry={onRetry} />}
        </div>
      </article>
    )
  }

  return (
    <article className={`message assistant${message.stopped ? ' stopped' : ''}`}>
      <ToolTrace tools={message.tools ?? []}
                 threadId={threadId}
                 replayed={message.replayed} />
      {message.content
        ? <Markdown text={message.content}
                    citations={message.citations}
                    onCite={onCite} />
        : !message.error && !message.stopped && (
          <p className="thinking">
            Thinking<Dots />
            {since !== null && <Elapsed since={since} />}
          </p>
        )}
      {message.stopped && <p className="stopped-note">Stopped</p>}
      {message.error && (
        <div className="failed">
          <p className="error">{message.error}</p>
          {onRetry && <Retry plain onRetry={onRetry} />}
        </div>
      )}
      <Citations citations={message.citations ?? []} onCite={onCite} />
      {/* Hidden while thinking; the elapsed counter shows instead. */}
      {(message.content || message.error || message.stopped) && (
        <p className="timing">
          <Clock at={message.at} />
          {message.ms !== undefined && (
            <span className="took">{formatDuration(message.ms)}</span>
          )}
          {since !== null && <Elapsed since={since} />}
          {message.usage && <Usage usage={message.usage} />}
          {/* Copy on every answer; retry icon only when the error block
              isn't already showing "Try again". */}
          {message.content && <Copy text={message.content} />}
          {onRetry && !message.error && <Retry onRetry={onRetry} />}
        </p>
      )}
    </article>
  )
})

/** Animated ellipsis.  Three elements, since animating `content` is not portable. */
function Dots() {
  return (
    <span className="dots" aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  )
}

/** Retry button: an icon, or "Try again" text with `plain` (beside an error). */
function Retry({ plain, onRetry }: { plain?: boolean; onRetry: () => void }) {
  return (
    <button className={plain ? 'retry plain' : 'retry'}
            onClick={onRetry}
            title="Ask this question again"
            aria-label="Ask this question again">
      <RetryIcon />
      {plain && 'Try again'}
    </button>
  )
}

/**
 * Copy the raw markdown, dotted section ids included.  Shows a tick for
 * 1.6s once the write resolves.
 */
function Copy({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const clear = setTimeout(() => setCopied(false), 1600)
    return () => clearTimeout(clear)
  }, [copied])

  const label = copied ? 'Copied' : 'Copy this answer'
  return (
    <button className={copied ? 'copy copied' : 'copy'}
            onClick={() => {
              // Absent outside a secure context, or may be denied.
              navigator.clipboard?.writeText(text)
                .then(() => setCopied(true))
                .catch(() => setCopied(false))
            }}
            title={label}
            aria-label={label}>
      {copied ? <TickIcon /> : <CopyIcon />}
    </button>
  )
}

function Citations({ citations, onCite }: {
  citations: Citation[]
  onCite: (id: string) => void
}) {
  if (citations.length === 0) return null
  return (
    <div className="citations">
      {/* Numbered to match the prose; the section id is in the title. */}
      {citations.map((citation, index) => (
        <button key={citation.section_id} className="chip"
                title={`SRD section ${citation.section_id}`}
                onClick={() => onCite(citation.section_id)}>
          <span className="chip-id">{index + 1}</span>
          {citation.heading}
        </button>
      ))}
    </div>
  )
}
