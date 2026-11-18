/**
 * An answer rendered as markdown, with `[11.2.114]` citations shown as
 * numbered buttons, one per id when several share a bracket
 * (`[9.7.6, 9.7.7]`).  Citations are rewritten to `#cite-` links before
 * parsing, so they work inside tables and lists too.
 */

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Citation } from '../api'

const CITATION = /\[(\d+(?:\.\d+)+(?:\s*[,;]\s*\d+(?:\.\d+)+)*)\]/g
// Between the ids of one citation.
const SEPARATOR = /\s*[,;]\s*/

type Props = {
  text: string
  citations?: Citation[]
  onCite: (sectionId: string) => void
}

/**
 * Section id to display number.  Uses the resolved `citations` once they
 * arrive (so unresolved ids get no number), and order of appearance in
 * `text` while streaming.
 */
export function numbering(text: string, citations?: Citation[]): Map<string, number> {
  if (citations?.length) {
    return new Map(citations.map((citation, index) =>
      [citation.section_id, index + 1]))
  }
  const order = new Map<string, number>()
  for (const [, ids] of text.matchAll(CITATION)) {
    for (const id of ids.split(SEPARATOR)) {
      if (!order.has(id)) order.set(id, order.size + 1)
    }
  }
  return order
}

export function Markdown({ text, citations, onCite }: Props) {
  const order = numbering(text, citations)
  const headings = new Map((citations ?? []).map((c) => [c.section_id, c.heading]))

  // Unresolved ids stay as written, unlinked; in a bracket with resolved
  // ones, each keeps a bracket of its own.
  const linked = text.replace(CITATION, (whole, ids: string) => {
    const each = ids.split(SEPARATOR)
    if (!each.some((id) => order.has(id))) return whole
    return each.map((id) =>
      order.has(id) ? `[${order.get(id)}](#cite-${id})` : `[${id}]`).join(' ')
  })

  return (
    <div className="prose">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children, ...rest }) {
            if (href?.startsWith('#cite-')) {
              const id = href.slice('#cite-'.length)
              const heading = headings.get(id)
              return (
                <button className="cite" onClick={() => onCite(id)}
                        title={heading ? `${heading} (${id})`
                                       : `Open SRD section ${id}`}>
                  {children}
                </button>
              )
            }
            return <a href={href} target="_blank" rel="noreferrer" {...rest}>
              {children}
            </a>
          },
        }}
      >
        {linked}
      </ReactMarkdown>
    </div>
  )
}
