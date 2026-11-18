/**
 * The right-hand panel.  Page tab: the whole PDF, under a folder path to the
 * cited section, whose lines are boxed in place.  Graph tab: the cited
 * node's neighbourhood, or the book's with nothing cited.
 */

import { lazy, Suspense, useEffect, useState } from 'react'
import { loadNeighbourhood, loadSource, type SourceExcerpt } from '../api'
import { useStored } from '../shared/useStored'
import { GraphView } from './graph/GraphView'
import { SectionTree } from './page/SectionTree'

// pdf.js is most of the bundle; load it when the panel first needs it.
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
  /** Changes on every citation, so citing the open section again scrolls. */
  visit: number
  tab: Tab
  onTab: (tab: Tab) => void
  onClose: () => void
  /** A section id, or null for the whole book. */
  onNavigate: (sectionId: string | null) => void
}

export function SidePanel({ sectionId, visit, tab, onTab, onClose, onNavigate }: Props) {
  const [excerpt, setExcerpt] = useState<SourceExcerpt | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [roots, setRoots] = useState<{ id: string; heading: string }[] | null>(null)
  const [rootsError, setRootsError] = useState<string | null>(null)
  const [zoom, setZoom] = useStored('page-zoom', DEFAULT_ZOOM)
  const [depth, setDepth] = useStored('graph-depth', DEFAULT_DEPTH)
  // `nth` changes on every jump so repeating a page number still scrolls.
  const [jump, setJump] = useState<{ page: number; nth: number } | null>(null)
  const jumpTo = (page: number) =>
    setJump((last) => ({ page, nth: (last?.nth ?? 0) + 1 }))

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

  // The top-level sections are the book seed's first ring in the graph.
  const needsRoots = tab === 'page' && !sectionId && roots === null
  useEffect(() => {
    if (!needsRoots) return
    let live = true
    loadNeighbourhood(null, 1)
      .then((book) => {
        if (!live) return
        setRoots(book.nodes
          .filter((node) => node.depth === 1 && node.section_id)
          .map((node) => ({ id: node.section_id!, heading: node.name ?? node.section_id! }))
          .sort((a, b) => Number(a.id) - Number(b.id)))
      })
      .catch((problem) => { if (live) setRootsError(String(problem)) })
    return () => { live = false }
  }, [needsRoots])

  return (
    <aside className="panel">
      <header className="panel-head">
        <div className="tabs">
          <button className={tab === 'page' ? 'on' : ''}
                  onClick={() => onTab('page')}>Page</button>
          <button className={tab === 'graph' ? 'on' : ''}
                  onClick={() => onTab('graph')}>Graph</button>
        </div>
        {tab === 'page' && (
          <PageJump onJump={jumpTo} />
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
      ) : (
        <>
          <SectionTree sectionId={sectionId} excerpt={excerpt} roots={roots ?? []}
                       loading={sectionId ? !excerpt && !error : roots === null && !rootsError}
                       error={sectionId ? error : rootsError}
                       onNavigate={(id) => {
                         onNavigate(id)
                         // Every other crumb scrolls to its section; the
                         // book's starts on page 1.
                         if (id === null) jumpTo(1)
                       }} />
          {/* The same element with or without a citation, so citing never
              remounts the book's 364 pages. */}
          <div className="panel-body">
            <Suspense fallback={<p className="muted">Loading the book…</p>}>
              <PdfBook zoom={zoom} excerpt={excerpt} visit={visit} jumpTo={jump} />
            </Suspense>
          </div>
        </>
      )}
    </aside>
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
