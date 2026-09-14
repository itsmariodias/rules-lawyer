/**
 * The right-hand panel: the page a citation was printed on, and the graph
 * around it.
 *
 * It opens from the toolbar as well as from a citation, so it has to be
 * useful with nothing selected: with no passage open the Page tab is the
 * whole book, browsable from page one, and a citation is that same reader
 * turned to a page with its lines boxed. Which tab is showing is the
 * shell's, since the toolbar picks it too.
 *
 * The source view is a facsimile rather than the extracted markdown. The
 * markdown is what the pipeline *derived*; the page is what the book
 * actually says, and a citation you can check against the original is worth
 * more than one you have to trust. `/source/{id}` still returns the text —
 * the parent and subsection links here come from the same response.
 */

import { lazy, Suspense, useEffect, useState } from 'react'
import { loadSource, type SourceExcerpt } from '../api'
import { useStored } from '../useStored'
import { GraphView } from './GraphView'

// pdf.js is most of the bundle and the panel starts closed, so it is
// fetched the first time a citation is opened rather than on page load.
const PdfPage = lazy(() =>
  import('./PdfPage').then((module) => ({ default: module.PdfPage })))
const PdfBook = lazy(() =>
  import('./PdfPage').then((module) => ({ default: module.PdfBook })))

// Fit is the default, and the panel is sized so that fitting is legible —
// at any other zoom the page is wider than the panel and half a column of
// the book sits off the edge. The rest are there for a closer look.
const ZOOMS = [1, 1.5, 2]
const DEFAULT_ZOOM = 1

/**
 * How far the graph reaches on opening.
 *
 * How deep is the reader's question, not ours — the same argument the panel
 * width is a drag handle for. Three is a screenful before anything is
 * clicked, and two is most of one on a hub. One is what the citation is
 * directly joined to, which is the question being asked on arrival; going
 * further is a click away, and the control is right there.
 */
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
  // Which page the book was last asked to jump to. A counter rides along so
  // that asking for the same page twice still scrolls.
  const [jump, setJump] = useState<{ page: number; nth: number } | null>(null)

  useEffect(() => {
    if (!sectionId) { setExcerpt(null); setError(null); return }
    setExcerpt(null)
    setError(null)
    loadSource(sectionId).then(setExcerpt).catch((e) => setError(String(e)))
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
        {tab === 'graph' && sectionId && (
          <div className="zooms" title="How many hops from the cited node">
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
                {excerpt.parent && (
                  <>
                    {' · in '}
                    <button className="link"
                            onClick={() => onNavigate(excerpt.parent!.id)}>
                      {excerpt.parent.heading}
                    </button>
                  </>
                )}
              </p>
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

/**
 * Somewhere to type a page number.
 *
 * 364 pages is more than anyone scrolls through, and the SRD's own index
 * and contents are printed in page numbers, so the way in is to type one.
 * It sits in the header rather than above the pages, where it would scroll
 * out of reach on the first flick of the wheel.
 */
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
