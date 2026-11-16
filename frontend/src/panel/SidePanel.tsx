/**
 * The right-hand panel.  Page tab: the whole PDF with nothing cited, or the
 * cited page with its lines boxed.  Graph tab: the cited node's
 * neighbourhood, or the book's with nothing cited.
 */

import { lazy, Suspense, useEffect, useState } from 'react'
import { loadSource, type SourceExcerpt } from '../api'
import { useStored } from '../shared/useStored'
import { GraphView } from './graph/GraphView'

// pdf.js is most of the bundle; load it when the panel first needs it.
const PdfPage = lazy(() =>
  import('./page/PdfPage').then((module) => ({ default: module.PdfPage })))
const PdfBook = lazy(() =>
  import('./page/PdfPage').then((module) => ({ default: module.PdfBook })))

const ZOOMS = [1, 1.5, 2]
const DEFAULT_ZOOM = 1

// Graph depth defaults to 1: at 2 a hub already fills the panel.
const DEPTHS = [1, 2, 3]
const DEFAULT_DEPTH = 1

export type Tab = 'page' | 'graph'

type Props = {
  sectionId: string | null
  tab: Tab
  onTab: (tab: Tab) => void
  onClose: () => void
  onNavigate: (sectionId: string) => void
}

export function SidePanel({ sectionId, tab, onTab, onClose, onNavigate }: Props) {
  const [excerpt, setExcerpt] = useState<SourceExcerpt | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [zoom, setZoom] = useStored('page-zoom', DEFAULT_ZOOM)
  const [depth, setDepth] = useStored('graph-depth', DEFAULT_DEPTH)
  // `nth` changes on every jump so repeating a page number still scrolls.
  const [jump, setJump] = useState<{ page: number; nth: number } | null>(null)

  useEffect(() => {
    if (!sectionId) { setExcerpt(null); setError(null); return }
    // A source that answers after a later citation's is dropped.
    let live = true
    setExcerpt(null)
    setError(null)
    loadSource(sectionId)
      .then((found) => { if (live) setExcerpt(found) })
      .catch((problem) => { if (live) setError(String(problem)) })
    return () => { live = false }
  }, [sectionId])

  return (
    <aside className="panel">
      <header className="panel-head">
        <div className="tabs">
          <button className={tab === 'page' ? 'on' : ''}
                  onClick={() => onTab('page')}>Page</button>
          <button className={tab === 'graph' ? 'on' : ''}
                  onClick={() => onTab('graph')}>Graph</button>
        </div>
        {tab === 'page' && !sectionId && (
          <PageJump onJump={(page) =>
            setJump((last) => ({ page, nth: (last?.nth ?? 0) + 1 }))} />
        )}
        {tab === 'page' && (
          <div className="zooms">
            {ZOOMS.map((level) => (
              <button key={level} className={zoom === level ? 'on' : ''}
                      onClick={() => setZoom(level)}>
                {level === 1 ? 'Fit' : `${level}×`}
              </button>
            ))}
          </div>
        )}
        {tab === 'graph' && (
          <div className="zooms" title="How many hops from the centre">
            {DEPTHS.map((hops) => (
              <button key={hops} className={depth === hops ? 'on' : ''}
                      onClick={() => setDepth(hops)}>
                {hops} hop{hops === 1 ? '' : 's'}
              </button>
            ))}
          </div>
        )}
        <button className="close" onClick={onClose} aria-label="Close panel">×</button>
      </header>

      {tab === 'graph' ? (
        <div className="panel-body graph-pane">
          <GraphView sectionId={sectionId} depth={depth}
                     onOpenPage={(id) => { onNavigate(id); onTab('page') }} />
        </div>
      ) : !sectionId ? (
        <div className="panel-body">
          <Suspense fallback={<p className="muted">Loading the book…</p>}>
            <PdfBook zoom={zoom} jumpTo={jump} />
          </Suspense>
        </div>
      ) : (
        <div className="panel-body">
          {error && <p className="error">{error}</p>}
          {!excerpt && !error && <p className="muted">Loading…</p>}
          {excerpt && (
            <>
              <h2>{excerpt.heading ?? excerpt.section_id}</h2>
              <p className="meta">
                <code>{excerpt.section_id}</code>
                {excerpt.entity_type && <span> · {excerpt.entity_type}</span>}
              </p>
              <Breadcrumb excerpt={excerpt} onNavigate={onNavigate} />
              <Suspense fallback={<p className="muted">Loading the page…</p>}>
                <PdfPage excerpt={excerpt} zoom={zoom} />
              </Suspense>
              {excerpt.children.length > 0 && (
                <nav className="children">
                  <h3>Subsections</h3>
                  <ul>
                    {excerpt.children.map((child) => (
                      <li key={child.id}>
                        <button className="link"
                                onClick={() => onNavigate(child.id)}>
                          {child.heading}
                        </button>
                      </li>
                    ))}
                  </ul>
                </nav>
              )}
            </>
          )}
        </div>
      )}
    </aside>
  )
}

/** The cited section's path from its top-level section, ancestors clickable. */
function Breadcrumb({ excerpt, onNavigate }: {
  excerpt: SourceExcerpt
  onNavigate: (sectionId: string) => void
}) {
  const ancestors = excerpt.ancestors ?? []
  if (ancestors.length === 0) return null
  return (
    <nav className="crumbs" aria-label="Location in the book">
      <ol>
        {ancestors.map((ancestor) => (
          <li key={ancestor.id}>
            <button className="link" title={ancestor.id}
                    onClick={() => onNavigate(ancestor.id)}>
              {ancestor.heading}
            </button>
          </li>
        ))}
        <li aria-current="location">
          {excerpt.heading ?? excerpt.section_id}
        </li>
      </ol>
    </nav>
  )
}

function PageJump({ onJump }: { onJump: (page: number) => void }) {
  const [value, setValue] = useState('')
  return (
    <form className="page-jump"
          onSubmit={(event) => {
            event.preventDefault()
            const page = Number(value)
            if (Number.isInteger(page) && page > 0) onJump(page)
          }}>
      <label htmlFor="page-jump">Page</label>
      <input id="page-jump" type="number" min={1} inputMode="numeric"
             value={value} placeholder="1"
             onChange={(event) => setValue(event.target.value)} />
      <button type="submit" disabled={!value.trim()}>Go</button>
    </form>
  )
}
