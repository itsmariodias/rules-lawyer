/**
 * The assistant's answer, with its citations made clickable.
 *
 * The model writes citations as bare `[11.2.114]`, which is not markdown.
 * Rewriting them into links before parsing is what lets `react-markdown`
 * handle them, and doing it as a rewrite rather than a custom text renderer
 * means a citation inside a table cell or a list item works the same way.
 *
 * **The id is what the model writes and a number is what a reader sees.**
 * The section id has to be the thing in the text, because the model can copy
 * it out of a tool result and because an invented one resolves to nothing
 * and is caught; a model asked to number its own sources renumbers them
 * halfway through a list, and a wrong `[2]` is indistinguishable from a
 * right one. But `11.2.114` means nothing to a reader and appears five times
 * in a four-line answer, so the id stays the key and the prose gets `[1]`.
 * The list underneath is the legend.
 */

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import type { Citation } from '../api'

const CITATION = /\[(\d+(?:\.\d+)+)\]/g

type Props = {
  text: string
  /** Resolved against the book, in order of first appearance. */
  citations?: Citation[]
  onCite: (sectionId: string) => void
}

/**
 * Which number each cited section gets, and which ids get one at all.
 *
 * Once the citations have arrived they decide it: they are the ones checked
 * against the book, already deduplicated in order of first appearance, so
 * the list and the prose cannot disagree. Until then the text is all there
 * is, and numbering from it keeps the answer readable while it streams.
 */
export function numbering(text: string, citations?: Citation[]): Map<string, number> {
  if (citations?.length) {
    return new Map(citations.map((citation, index) =>
      [citation.section_id, index + 1]))
  }
  const order = new Map<string, number>()
  for (const [, id] of text.matchAll(CITATION)) {
    if (!order.has(id)) order.set(id, order.size + 1)
  }
  return order
}

export function Markdown({ text, citations, onCite }: Props) {
  const order = numbering(text, citations)
  const headings = new Map((citations ?? []).map((c) => [c.section_id, c.heading]))

  // An id nothing resolved is left as the model wrote it, unlinked. It used
  // to draw as a live chip that opened nothing, which is a worse lie than
  // showing that the model cited something the book does not have.
  const linked = text.replace(CITATION, (whole, id) =>
    order.has(id) ? `[${order.get(id)}](#cite-${id})` : whole)

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
