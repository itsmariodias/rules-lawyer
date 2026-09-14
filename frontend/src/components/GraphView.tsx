/**
 * The graph, drawn.
 *
 * The Page tab answers "what does the book say here"; this one answers "what
 * is this connected to", which is the question stage 2 exists to make
 * askable and which nothing in the UI could ask until now.
 *
 * **It never draws the whole graph.** 4260 nodes is not a picture, it is a
 * hairball, and a single hub — Poison damage, referenced from 121 places —
 * would swamp the panel on its own. So a citation opens on *its* node and
 * the edges immediately around it, and everything further is a click: the
 * server caps the fan-out per relationship type and the node count in total,
 * says what it capped, and this view spends those clicks one node at a time.
 * Expanding merges into what is already on screen rather than replacing it,
 * so following a chain reads as walking rather than as a series of unrelated
 * pictures.
 *
 * **The layout is ours.** A force simulation over sixty nodes is a hundred
 * lines and no dependency; d3-force would be the whole library for the one
 * function of it we want. The seed is pinned at the centre, because the
 * reader came here from a citation and the thing they cited should not
 * wander off while they watch.
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

/**
 * The spring along every edge, and friction.
 *
 * The spring's *rest length* is not a constant: twelve nodes in a tall
 * panel and sixty in a short one want very different pictures, and a fixed
 * length gives the first a knot in the middle of an empty page. So it comes
 * from the room available and the number of things to put in it — see
 * `restLength` — and the repulsion that balances it follows from that.
 * Sizing the layout is better than magnifying it afterwards: zoom scales the
 * circles and the type along with the distances, and a graph blown up to
 * fill a panel is just a graph with enormous labels.
 */
const SPRING = 0.045
const FRICTION = 0.86
const CENTRING = 0.012

/** The simulation cools rather than running forever behind a still picture. */
const COOL = 0.992
const COLD = 0.004

const ZOOM_RANGE = [0.25, 3] as const
/**
 * How much wider a hub gets when it is asked for more.
 *
 * The server samples deterministically, so asking again for the same `fan`
 * returns the same neighbours and reads as a broken button. The ask is
 * therefore derived from the picture rather than from a click count: twice
 * whatever is already drawn from that node's largest group. That matters on
 * the *first* click too — a node two hops out was already sampled at the
 * default fan on the way in, so expanding it at the default fan would show
 * nothing new.
 */
const WIDEN = 2
const FAN = 8

type Props = {
  /** The section the panel was opened on, or null when nothing is cited. */
  sectionId: string | null
  depth: number
  /** Open a node on the Page tab; only nodes that are sections can be. */
  onOpenPage: (sectionId: string) => void
}

export function GraphView({ sectionId, depth, onOpenPage }: Props) {
  const [graph, setGraph] = useState<Neighbourhood | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  // How many times each node has been expanded, not merely whether: it is
  // what decides how much wider the next ask is.
  const [expanded, setExpanded] = useState<Record<string, number>>({})

  // Bodies are the simulation's; positions are what it publishes. Sixty
  // nodes a frame is nothing to re-render, and keeping the drawing on state
  // means the picture is a function of state like everything else here.
  const bodies = useRef(new Map<string, Body>())
  const [places, setPlaces] = useState<Places>({})
  const box = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [view, setView] = useState<View>({ x: 0, y: 0, k: 1 })
  // How much of the canvas the details card is covering. Measured rather
  // than assumed: the card grows a row per relationship type on the
  // selected node, so a creature's is twice a leaf section's.
  const [reserved, setReserved] = useState(0)
  const card = useRef<HTMLElement>(null)
  // The simulation writes into `places`; this is only how it asks React to
  // look again, so a frame costs one render and no reconciliation of state.

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

  // A fresh seed is a fresh picture: positions, selection and the record of
  // what has been expanded all belong to the graph that is on screen.
  useEffect(() => {
    if (!sectionId) { setGraph(null); return }
    let live = true
    setBusy(true)
    setError(null)
    bodies.current = new Map()
    setPlaces({})
    setExpanded({})
    setSelected(null)
    setView({ x: 0, y: 0, k: 1 })
    framed.current = false
    loadNeighbourhood({ section: sectionId }, depth)
      .then((found) => { if (live) { setGraph(found); setSelected(found.root) } })
      .catch((problem) => { if (live) setError(String(problem)) })
      .finally(() => { if (live) setBusy(false) })
    return () => { live = false }
  }, [sectionId, depth])

  // Panning and zooming are one-way without this: the reader can always ask
  // for the framing back, which is also what the Page tab's Fit does. It
  // has to fit *now* rather than only clear the flag, because by the time
  // anyone reaches for it the simulation has cooled and stopped and there
  // is no next frame to recompute anything.
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

  // The view transform is read inside pointer handlers that outlive the
  // render they were created in, so it is held as well as stored.
  const camera = useRef(view)
  useEffect(() => { camera.current = view }, [view])
  // Until the reader moves the picture themselves, it is framed for them.
  // After that it is theirs, and refitting under their hands would be the
  // application arguing with them.
  const framed = useRef(false)
  // Handing out the setting rather than the ref: the simulation reads it
  // live inside its own loop, but nothing else needs more than to say "the
  // reader has taken over".
  const claim = useCallback(() => { framed.current = true }, [])

  useSimulation(graph, bodies.current, size, setPlaces, setView, framed,
                reserved)

  const drag = useDrag(bodies.current, camera, box, claim)
  const pan = usePan(setView, camera, box, claim)

  // Positions are published by the simulation's effect, so the first paint
  // after a load has none and draws nothing.
  const seeded = graph && Object.keys(places).length > 0 ? graph : null

  if (!sectionId) {
    return (
      <div className="graph-empty">
        <p>Nothing selected.</p>
        <p className="muted">
          Cite a passage — or open one from the Page tab — and its node, the
          nodes around it and the edges between them are drawn here.
        </p>
      </div>
    )
  }

  const node = graph?.nodes.find((n) => n.uid === selected) ?? null
  // An edge stops at the rim of the node it points at, not at its centre,
  // so the arrowhead lands beside the circle instead of under it.
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
               role="img" aria-label="The graph around the cited section">
            <defs>
              {/* One marker per state: SVG markers cannot inherit the
                  stroke of the line they cap. */}
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

/** How far short of the target's centre the arrowhead has to stop. */
const ARROW = 6

function Link({ edge, places, radius, active }: {
  edge: GraphEdge
  places: Places
  /** The radius of the node this edge points at. */
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

/**
 * The type of an edge, drawn over the picture rather than in it.
 *
 * The type is the whole point of an edge, but eleven of them at once is a
 * thicket, so only the selected node's are labelled — and they are drawn in
 * a pass after the nodes, because a label that disappears under the circle
 * it describes is worse than no label.
 */
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
  // `data-node` is filled for a passage the book printed and hollow for a
  // node stage 2 derived from one. Both are real: "Alignment" is a glossary
  // *section* and a glossary *term*, and two identical circles beside each
  // other read as a duplicate rather than as two things.
  return (
    <g className={`dot ${selected ? 'on' : ''} ${root ? 'root' : ''}`}
       data-kind={kindOf(node)}
       data-node={node.section_id ? 'printed' : 'derived'}
       transform={`translate(${at.x},${at.y})`}
       onPointerDown={(event) => { onSelect(node.uid); onDrag(node.uid, event) }}>
      <circle r={radius} />
      {/* A node with edges the server did not send says so, rather than
          looking like a node with nothing left to show. */}
      {hidden > 0 && !grown && <circle className="more" r={radius + 3.5} />}
      <text y={radius + 12} textAnchor="middle">{clip(node.name)}</text>
    </g>
  )
}

/**
 * What is known about the selected node, and the two things to do with it.
 *
 * "Open page" is missing rather than disabled on a node that is not a
 * section: a damage type has no passage of its own, and a button that can
 * never work is worse than no button.
 */
function Details({ ref, node, graph, asked, busy, onExpand, onOpenPage }: {
  ref: React.RefObject<HTMLElement | null>
  node: GraphNode
  graph: Neighbourhood
  /** How many times this node has already been expanded. */
  asked: number
  busy: boolean
  /** Called with the fan to ask for, which the card is what can work out. */
  onExpand: (fan: number) => void
  onOpenPage: (sectionId: string) => void
}) {
  const drawn = graph.edges.filter(
    (edge) => edge.source === node.uid || edge.target === node.uid).length
  const hidden = countHidden(graph, node.uid)
  const groups = connections(graph, node.uid)
  // Twice the biggest group already on screen, so the ask is always wider
  // than what it would return unchanged.
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
      {/* What the node says, so selecting one answers "and what is that?"
          in place. The Page tab is where the passage is read in full; this
          is only enough to recognise it by. */}
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
        {/* Three states, because they are three different situations: a
            node nothing has been asked of, a hub with more to give, and one
            whose edges are all already drawn. */}
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
 * Give every node that has not got one a starting position.
 *
 * The seed is pinned dead centre and everything else lands on a ring around
 * whichever drawn node introduced it — so an expansion visibly grows out of
 * the node that was clicked, and a simulation that starts from a plausible
 * arrangement settles instead of exploding.
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
    const angle = index * 2.399  // the golden angle: no two land together
    const rest = restLength(size, graph.nodes.length)
    bodies.set(node.uid, {
      x: from.x + Math.cos(angle) * rest,
      y: from.y + Math.sin(angle) * rest,
      vx: 0, vy: 0, pinned: false,
    })
  })
}

/**
 * Repulsion between every pair, a spring along every edge, a pull to the
 * centre, and friction — run until it cools.
 *
 * O(n²) is the right algorithm here: the server caps the picture at sixty
 * nodes, and a Barnes-Hut tree for sixty bodies is more code and slower.
 */
function useSimulation(graph: Neighbourhood | null, bodies: Map<string, Body>,
                       size: { width: number; height: number },
                       publish: (places: Places) => void,
                       frame_: (view: View) => void,
                       framed: React.RefObject<boolean>,
                       reserved: number) {
  useEffect(() => {
    if (!graph || !size.width) return
    // New nodes are placed here rather than during a render: the picture is
    // laid out by this effect, and giving a node its first position is part
    // of laying it out.
    place(graph, bodies, size)
    const rest = restLength(size, graph.nodes.length)
    // Balanced against the spring: repulsion falls off as 1/d², so scaling
    // it with the rest length squared keeps the two in the same proportion
    // whatever size the picture is being drawn at.
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
          // Two nodes exactly on top of each other have no direction to be
          // pushed apart in; any direction will do, so long as it is one.
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
      // Fitting every frame rather than once at the end, so the picture is
      // framed while it settles instead of snapping when it stops.
      if (!framed.current) frame_(fit(points, size, reserved))
      // A settled picture is a still one: the loop stops rather than
      // repainting sixty circles for ever behind an idle reader.
      if (alpha > COLD) frame = requestAnimationFrame(tick)
    }

    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [graph, bodies, size, publish, frame_, framed, reserved])
}

/**
 * Dragging a node.
 *
 * The listeners go on the window, for the reason the panel's resizer does:
 * a pointer routinely leaves a 20px circle mid-drag, and the drag must not
 * end when it does. A dragged node is pinned while it is held and let go
 * again after, so the reader can tease a cluster apart without the layout
 * fighting them and without freezing it.
 */
function useDrag(bodies: Map<string, Body>,
                 camera: React.RefObject<View>,
                 box: React.RefObject<HTMLDivElement | null>,
                 claim: () => void) {
  return useCallback((uid: string, event: React.PointerEvent) => {
    const point = bodies.get(uid)
    const frame = box.current?.getBoundingClientRect()
    if (!point || !frame) return
    event.stopPropagation()  // otherwise the background pan starts too
    const wasPinned = point.pinned
    point.pinned = true
    // Moving a node is arranging the picture, so the framing stops being
    // ours to redo.
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
      // Keep whatever is under the pointer under the pointer.
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

/* ── plumbing ──────────────────────────────────────────────────────── */


