/**
 * The assistant's answer, with its citations made clickable.
 *
 * The model writes citations as bare `[11.2.114]`, which is not markdown.
 * Rewriting them into links before parsing is what lets `react-markdown`
 * handle them — and doing it as a rewrite rather than a custom text renderer
 * means a citation inside a table cell or a list item works the same way.
 */

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const CITATION = /\[(\d+(?:\.\d+)+)\]/g

type Props = { text: string; onCite: (sectionId: string) => void }

export function Markdown({ text, onCite }: Props) {
  const linked = text.replace(CITATION, (_, id) => `[${id}](#cite-${id})`)

  return (
    <div className="prose">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children, ...rest }) {
            if (href?.startsWith('#cite-')) {
              const id = href.slice('#cite-'.length)
              return (
                <button className="cite" onClick={() => onCite(id)}
                        title={`Open SRD section ${id}`}>
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
