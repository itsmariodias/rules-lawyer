/**
 * Force-directed view of the cited node's neighbourhood, or with nothing
 * cited, of the book and its top-level sections.  Expanding a node merges
 * its neighbours into the current picture.  The seed is pinned at the
 * centre; the simulation stops once it cools.
 */

import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import {
  loadNeighbourhood,
  type GraphEdge,
  type GraphNode,
  type Neighbourhood,
} from '../api'
import {
  clip, connections, countHidden, fit, kindOf, labelled, merge, radiusOf,
  restLength, type Body, type Places, type View,
} from './graph-layout'

// Rest length comes from `restLength`; repulsion is derived from it.
const SPRING = 0.045
const FRICTION = 0.86
const CENTRING = 0.012

const COOL = 0.992
const COLD = 0.004

const ZOOM_RANGE = [0.25, 3] as const
/**
 * Expansion asks for `WIDEN` times the node's largest drawn group.  The
 * server's sample is deterministic, so repeating a fan returns nothing new,
 * including on a first click on a node already sampled at the default fan.
 */
const WIDEN = 2
const FAN = 8

type Props = {
  sectionId: string | null
  depth: number
  onOpenPage: (sectionId: string) => void
}

export function GraphView({ sectionId, depth, onOpenPage }: Props) {
  const [graph, setGraph] = useState<Neighbourhood | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  // Expansion count per node.
  const [expanded, setExpanded] = useState<Record<string, number>>({})

  // Simulation state in a ref; positions published to state each frame.
  const bodies = useRef(new Map<string, Body>())
  const [places, setPlaces] = useState<Places>({})
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 })
  // Measured height of the details card, which overlays the canvas.
  const [reserved, setReserved] = useState(0)
  const card = useRef<HTMLElement>(null)

  useEffect(() => {
    const element = box.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width,
                height: entry.contentRect.height }))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const element = card.current
    if (!element) { setReserved(0); return }
    const observer = new ResizeObserver(([entry]) =>
      setReserved(entry.contentRect.height + 24))
    observer.observe(element)
    return () => observer.disconnect()
  }, [selected, graph])

  useEffect(() => {
    let live = true
    setBusy(true)
    setError(null)
    bodies.current = new Map()
    setPlaces({})
    setExpanded({})
    setSelected(null)
    setView({ x: 0, y: 0, k: 1 })
    framed.current = false
    loadNeighbourhood(sectionId ? { section: sectionId } : null, depth)
      .then((found) => { if (live) { setGraph(found); setSelected(found.root) } })
      .catch((problem) => { if (live) setError(String(problem)) })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [sectionId, depth])

  // Fits immediately as well as clearing the flag: a cooled simulation has
  // no next frame to do it.
  const refit = useCallback(() => {
    framed.current = false
    const points = (graph?.nodes ?? [])
      .map((item) => bodies.current.get(item.uid))
      .filter((point): point is Body => Boolean(point))
    if (points.length && size.width) setView(fit(points, size, reserved))
  }, [graph, size, reserved])

  const expand = useCallback(async (uid: string, fan: number) => {
    setBusy(true)
    try {
      const more = await loadNeighbourhood({ node: uid }, 1, fan)
      setExpanded((seen) => ({ ...seen, [uid]: (seen[uid] ?? 0) + 1 }))
      setGraph((current) => (current ? merge(current, more) : more))
      setError(null)
    } catch (problem) {
      setError(String(problem))
    } finally {
      setBusy(false)
    }
  }, [])

  // Mirror of `view` for pointer handlers that outlive their render.
  const camera = useRef(view)
  useEffect(() => { camera.current = view }, [view])
  // Set once the user pans, zooms or drags; auto-fitting then stops.
  const framed = useRef(false)
  const claim = useCallback(() => { framed.current = true }, [])

  useSimulation(graph, bodies.current, size, setPlaces, setView, framed,
                reserved)

  const drag = useDrag(bodies.current, camera, box, claim)
  const pan = usePan(setView, camera, box, claim)

  // Null until the simulation has published positions.
  const seeded = graph && Object.keys(places).length > 0 ? graph : null

  const node = graph?.nodes.find((n) => n.uid === selected) ?? null
  // Edges end at the target's rim so the arrowhead is visible.
  const radii: Record<string, number> = {}
  for (const item of graph?.nodes ?? []) radii[item.uid] = radiusOf(item)

  return (
    <div className="graph">
      <div className="graph-canvas" ref={box}
           onPointerDown={pan.onPointerDown} onWheel={pan.onWheel}>
        <button className="graph-refit" onClick={refit}
                title="Fit the graph to the panel">Fit</button>
        {error && <p className="error graph-note">{error}</p>}
        {!graph && !error && <p className="muted graph-note">Loading…</p>}
        {seeded && (
          <svg width={size.width} height={size.height}
               role="img"
               aria-label={sectionId ? 'The graph around the cited section'
                                     : 'The book and its top-level sections'}>
            <defs>
              {/* SVG markers cannot inherit stroke, so one per state. */}
              {['edge', 'edge-on'].map((name) => (
                <marker key={name} id={`arrow-${name}`} viewBox="0 0 8 8"
                        refX="7" refY="4" markerWidth="7" markerHeight="7"
                        orient="auto-start-reverse">
                  <path className={name} d="M0 0.5 L8 4 L0 7.5 z" />
                </marker>
              ))}
            </defs>
            <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
              {seeded.edges.map((edge) => (
                <Link key={edge.uid} edge={edge} places={places}
                      radius={radii[edge.target] ?? 0}
                      active={edge.source === selected
                              || edge.target === selected} />
              ))}
              {seeded.nodes.map((item) => (
                <Dot key={item.uid} node={item} places={places}
                     root={item.uid === seeded.root}
                     selected={item.uid === selected}
                     grown={Boolean(expanded[item.uid])}
                     hidden={countHidden(seeded, item.uid)}
                     onSelect={setSelected} onDrag={drag} />
              ))}
              {labelled(seeded, selected).map((edge) => (
                <LinkLabel key={edge.uid} edge={edge} places={places} />
              ))}
            </g>
          </svg>
        )}
        {busy && graph && <p className="graph-note busy">Loading…</p>}
      </div>

      {node && (
        <Details ref={card} node={node} graph={seeded ?? graph!}
                 asked={expanded[node.uid] ?? 0} busy={busy}
                 onExpand={(fan) => void expand(node.uid, fan)}
                 onOpenPage={onOpenPage} />
      )}
      <Legend nodes={graph?.nodes ?? []} />
    </div>
  )
}

/* ── the picture ───────────────────────────────────────────────────── */

const ARROW = 6

function Link({ edge, places, radius, active }: {
  edge: GraphEdge
  places: Places
  /** Target node radius. */
  radius: number
  active: boolean
}) {
  const from = places[edge.source]
  const to = places[edge.target]
  if (!from || !to) return null
  const dx = to.x - from.x
  const dy = to.y - from.y
  const distance = Math.hypot(dx, dy) || 1
  const back = Math.min(radius + ARROW, distance - 1)
  return (
    <g className={`link ${active ? 'on' : ''}`}>
      <line x1={from.x} y1={from.y}
            x2={to.x - (dx / distance) * back}
            y2={to.y - (dy / distance) * back}
            markerEnd={`url(#arrow-${active ? 'edge-on' : 'edge'})`} />
    </g>
  )
}

/** An edge's type at its midpoint; rendered after the nodes so it stays on top. */
function LinkLabel({ edge, places }: { edge: GraphEdge; places: Places }) {
  const from = places[edge.source]
  const to = places[edge.target]
  if (!from || !to) return null
  return (
    <text className="link-label"
          x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 3}
          textAnchor="middle">{edge.type.toLowerCase()}</text>
  )
}

function Dot({ node, places, root, selected, grown, hidden, onSelect, onDrag }: {
  node: GraphNode
  places: Places
  root: boolean
  selected: boolean
  grown: boolean
  hidden: number
  onSelect: (uid: string) => void
  onDrag: (uid: string, event: React.PointerEvent) => void
}) {
  const at = places[node.uid]
  if (!at) return null
  const radius = radiusOf(node)
  // `data-node`: filled for sections, hollow for derived nodes, which can
  // share a name (the "Alignment" section and glossary term).
  return (
    <g className={`dot ${selected ? 'on' : ''} ${root ? 'root' : ''}`}
       data-kind={kindOf(node)}
       data-node={node.section_id ? 'printed' : 'derived'}
       transform={`translate(${at.x},${at.y})`}
       onPointerDown={(event) => { onSelect(node.uid); onDrag(node.uid, event) }}>
      <circle r={radius} />
      {/* Dashed halo: the server holds edges not yet fetched. */}
      {hidden > 0 && !grown && <circle className="more" r={radius + 3.5} />}
      <text y={radius + 12} textAnchor="middle">{clip(node.name)}</text>
    </g>
  )
}

/** The selected node's card.  "Open page" appears only for sections. */
function Details({ ref, node, graph, asked, busy, onExpand, onOpenPage }: {
  ref: React.RefObject<HTMLElement | null>
  node: GraphNode
  graph: Neighbourhood
  /** How many times this node has already been expanded. */
  asked: number
  busy: boolean
  /** Called with the fan to request. */
  onExpand: (fan: number) => void
  onOpenPage: (sectionId: string) => void
}) {
  const drawn = graph.edges.filter(
    (edge) => edge.source === node.uid || edge.target === node.uid).length
  const hidden = countHidden(graph, node.uid)
  const groups = connections(graph, node.uid)
  const fan = Math.max(FAN,
                       Math.max(0, ...groups.map((g) => g.drawn)) * WIDEN)
  return (
    <aside className="graph-details" ref={ref}>
      <h3>
        <span className="swatch" data-kind={kindOf(node)} />
        {node.name ?? '(unnamed)'}
      </h3>
      <p className="meta">
        {node.labels.join(' · ') || 'Section'}
        {node.section_id && <> · <code>{node.section_id}</code></>}
        {node.page !== null && <> · p.{node.page}</>}
      </p>
      {/* Summary, or facts for nodes with no prose. */}
      {node.summary && <p className="graph-summary">{node.summary}</p>}
      {!node.summary && node.facts.length > 0 && (
        <dl className="graph-facts">
          {node.facts.map((fact) => (
            <Fragment key={fact.name}>
              <dt>{fact.name}</dt>
              <dd>{fact.value}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      <p className="meta">
        {drawn} of {node.degree} edge{node.degree === 1 ? '' : 's'} drawn
        {hidden > 0 && <> · {hidden} not fetched</>}
      </p>
      <ul className="graph-edges">
        {groups.map((group) => (
          <li key={`${group.type}|${group.out}`}>
            <span className="arrow">{group.out ? '→' : '←'}</span>
            <code>{group.type.toLowerCase()}</code>
            <span className="count">
              {group.total > group.drawn
                ? `${group.drawn} of ${group.total}`
                : group.drawn}
            </span>
          </li>
        ))}
      </ul>
      <div className="graph-actions">
        {/* Expand / Show more / Expanded (nothing left to fetch). */}
        <button onClick={() => onExpand(fan)}
                disabled={busy || (asked > 0 && hidden === 0)}>
          {asked === 0 ? 'Expand' : hidden > 0 ? 'Show more' : 'Expanded'}
        </button>
        {node.section_id && (
          <button onClick={() => onOpenPage(node.section_id!)}>
            Open page
          </button>
        )}
      </div>
    </aside>
  )
}

function Legend({ nodes }: { nodes: GraphNode[] }) {
  const kinds = [...new Set(nodes.map(kindOf))].sort()
  if (kinds.length === 0) return null
  const derived = nodes.some((node) => !node.section_id)
  return (
    <ul className="graph-legend">
      {kinds.map((kind) => (
        <li key={kind}><span className="swatch" data-kind={kind} />{kind}</li>
      ))}
      {derived && (
        <li className="note">
          <span className="swatch" data-node="derived" />not a section
        </li>
      )}
    </ul>
  )
}

/* ── the layout ────────────────────────────────────────────────────── */

/**
 * Initial positions for new nodes: the seed pinned at the centre, others on
 * a golden-angle spiral around an already-placed neighbour.
 */
function place(graph: Neighbourhood, bodies: Map<string, Body>,
               size: { width: number; height: number }) {
  const cx = size.width / 2
  const cy = size.height / 2
  graph.nodes.forEach((node, index) => {
    if (bodies.has(node.uid)) return
    if (node.uid === graph.root) {
      bodies.set(node.uid, { x: cx, y: cy, vx: 0, vy: 0, pinned: true })
      return
    }
    const anchor = graph.edges.find(
      (edge) => (edge.source === node.uid && bodies.has(edge.target))
             || (edge.target === node.uid && bodies.has(edge.source)))
    const from = anchor
      ? bodies.get(anchor.source === node.uid ? anchor.target : anchor.source)!
      : { x: cx, y: cy }
    const angle = index * 2.399  // golden angle, radians
    const rest = restLength(size, graph.nodes.length)
    bodies.set(node.uid, {
      x: from.x + Math.cos(angle) * rest,
      y: from.y + Math.sin(angle) * rest,
      vx: 0, vy: 0, pinned: false,
    })
  })
}

/**
 * Pairwise repulsion, edge springs, centring and friction, until `alpha`
 * drops below `COLD`.  O(n²) is fine: the server caps the graph's size.
 */
function useSimulation(graph: Neighbourhood | null, bodies: Map<string, Body>,
                       size: { width: number; height: number },
                       publish: (places: Places) => void,
                       frame_: (view: View) => void,
                       framed: React.RefObject<boolean>,
                       reserved: number) {
  useEffect(() => {
    if (!graph || !size.width) return
    place(graph, bodies, size)
    const rest = restLength(size, graph.nodes.length)
    // Repulsion falls off as 1/d², so scale it by rest² to stay balanced.
    const repulsion = rest * rest * 0.58
    let alpha = 1
    let frame = 0

    const tick = () => {
      const points = graph.nodes
        .map((node) => bodies.get(node.uid))
        .filter((point): point is Body => Boolean(point))

      for (let i = 0; i < points.length; i++) {
        for (let j = i + 1; j < points.length; j++) {
          const a = points[i]
          const b = points[j]
          let dx = b.x - a.x
          let dy = b.y - a.y
          // Coincident nodes: push in a random direction.
          let distance = Math.hypot(dx, dy)
          if (distance < 0.5) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; distance = 0.5 }
          const push = Math.min(repulsion / (distance * distance), 40)
          const ux = (dx / distance) * push
          const uy = (dy / distance) * push
          a.vx -= ux; a.vy -= uy
          b.vx += ux; b.vy += uy
        }
      }

      for (const edge of graph.edges) {
        const a = bodies.get(edge.source)
        const b = bodies.get(edge.target)
        if (!a || !b) continue
        const dx = b.x - a.x
        const dy = b.y - a.y
        const distance = Math.hypot(dx, dy) || 1
        const pull = (distance - rest) * SPRING
        const ux = (dx / distance) * pull
        const uy = (dy / distance) * pull
        a.vx += ux; a.vy += uy
        b.vx -= ux; b.vy -= uy
      }

      const cx = size.width / 2
      const cy = size.height / 2
      for (const point of points) {
        if (point.pinned) { point.vx = 0; point.vy = 0; continue }
        point.vx += (cx - point.x) * CENTRING
        point.vy += (cy - point.y) * CENTRING
        point.vx *= FRICTION
        point.vy *= FRICTION
        point.x += point.vx * alpha
        point.y += point.vy * alpha
      }

      alpha *= COOL
      publish(Object.fromEntries(
        [...bodies].map(([uid, at]) => [uid, { x: at.x, y: at.y }])))
      // Fit every frame so the view follows the layout as it settles.
      if (!framed.current) frame_(fit(points, size, reserved))
      if (alpha > COLD) frame = requestAnimationFrame(tick)
    }

    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [graph, bodies, size, publish, frame_, framed, reserved])
}

/**
 * Drag a node, pinned while held.  Listeners are on the window so leaving
 * the circle mid-drag does not end it.
 */
function useDrag(bodies: Map<string, Body>,
                 camera: React.RefObject<View>,
                 box: React.RefObject<HTMLDivElement | null>,
                 claim: () => void) {
  return useCallback((uid: string, event: React.PointerEvent) => {
    const point = bodies.get(uid)
    const frame = box.current?.getBoundingClientRect()
    if (!point || !frame) return
    event.stopPropagation()  // don't also start the background pan
    const wasPinned = point.pinned
    point.pinned = true
    claim()

    const move = (moved: PointerEvent) => {
      const view = camera.current
      point.x = (moved.clientX - frame.left - view.x) / view.k
      point.y = (moved.clientY - frame.top - view.y) / view.k
      point.vx = 0
      point.vy = 0
    }
    const up = () => {
      point.pinned = wasPinned
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }, [bodies, camera, box, claim])
}

/** Wheel to zoom about the pointer, drag the background to pan. */
function usePan(setView: React.Dispatch<React.SetStateAction<View>>,
                camera: React.RefObject<View>,
                box: React.RefObject<HTMLDivElement | null>,
                claim: () => void) {
  const onWheel = useCallback((event: React.WheelEvent) => {
    const frame = box.current?.getBoundingClientRect()
    if (!frame) return
    claim()
    const px = event.clientX - frame.left
    const py = event.clientY - frame.top
    setView((current) => {
      const k = Math.min(ZOOM_RANGE[1],
                         Math.max(ZOOM_RANGE[0],
                                  current.k * Math.exp(-event.deltaY * 0.0015)))
      // Zoom about the pointer.
      const scale = k / current.k
      return { k, x: px - (px - current.x) * scale,
               y: py - (py - current.y) * scale }
    })
  }, [setView, box, claim])

  const onPointerDown = useCallback((event: React.PointerEvent) => {
    claim()
    const startX = event.clientX
    const startY = event.clientY
    const origin = { x: camera.current.x, y: camera.current.y }

    const move = (moved: PointerEvent) => {
      setView((current) => ({ ...current,
                              x: origin.x + (moved.clientX - startX),
                              y: origin.y + (moved.clientY - startY) }))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }, [setView, camera, claim])

  return { onWheel, onPointerDown }
}


