/** Pure layout helpers for `GraphView`: spring length, fit, colour kind, merge. */

import type { GraphEdge, GraphNode, Neighbourhood } from '../../api'

/** A simulated node. */
export type Body = { x: number; y: number; vx: number; vy: number
                     pinned: boolean }

/** Node positions published to React each frame. */
export type Places = Record<string, { x: number; y: number }>

/** Pan offset and zoom. */
export type View = { x: number; y: number; k: number }

export type Size = { width: number; height: number }

/* ── the spring ────────────────────────────────────────────────────── */

const REST_MIN = 92
const REST_MAX = 280

/** Spring rest length from the area per node, clamped to `REST_MIN..REST_MAX`. */
export function restLength(size: Size, nodes: number): number {
  const each = Math.sqrt((size.width * size.height) / Math.max(nodes, 2))
  return Math.max(REST_MIN, Math.min(REST_MAX, each * 0.75))
}

/* ── fitting ───────────────────────────────────────────────────────── */

// Fit never zooms out past FIT_MIN: labels are ~130 units wide and become
// unreadable, so a large graph overflows and is panned instead.
const MARGIN = 54
const FIT_MIN = 1
const FIT_MAX = 1.5

/** Label overhang past a node, in layout units: [each side, below]. */
const LABEL = [64, 20] as const

/**
 * The view that centres the nodes and their labels, zoom clamped to
 * `FIT_MIN..FIT_MAX`.  `bottom` is the height covered by the details card.
 */
export function fit(points: Body[], size: Size, bottom: number): View {
  if (points.length === 0) return { x: 0, y: 0, k: 1 }
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  const left = Math.min(...xs) - LABEL[0]
  const right = Math.max(...xs) + LABEL[0]
  const high = Math.min(...ys)
  const low = Math.max(...ys) + LABEL[1]
  const usable = Math.max(120, size.height - MARGIN * 2 - bottom)
  const k = Math.min(
    FIT_MAX,
    Math.max(FIT_MIN,
             Math.min((size.width - MARGIN * 2) / Math.max(right - left, 1),
                      usable / Math.max(low - high, 1))))
  return {
    k,
    x: size.width / 2 - k * (left + right) / 2,
    y: MARGIN + usable / 2 - k * (high + low) / 2,
  }
}

/* ── how a node is drawn ───────────────────────────────────────────── */

/**
 * Colour kind by label, first match wins, so order matters for multi-label
 * nodes.  An unlisted label draws grey; `backend/tests/test_docs.py` parses
 * this table and checks it against the mapper, so keep its shape.
 */
export const KINDS: [string, string[]][] = [
  ['creature', ['Creature', 'CreatureGroup']],
  ['ability', ['CreatureAbility']],
  ['spell', ['Spell']],
  ['item', ['MagicItem', 'Weapon', 'Armor', 'Gear', 'Poison', 'Equipment']],
  ['glossary', ['Condition', 'DamageType', 'PoisonType', 'Action',
                'AreaOfEffect', 'Hazard', 'Attitude', 'Definition',
                'GlossaryTerm']],
  ['class', ['Class', 'Subclass', 'ClassLevel', 'ClassFeature', 'Feat',
             'Species', 'Background', 'Origin']],
  ['rule', ['Rule', 'Trap', 'EnvironmentalEffect', 'Contagion', 'FrontMatter']],
  ['book', ['Book']],
]

export function kindOf(node: GraphNode): string {
  for (const [kind, labels] of KINDS) {
    if (labels.some((label) => node.labels.includes(label))) return kind
  }
  return 'section'
}

/** Radius grows with sqrt(degree), capped at 22. */
export const radiusOf = (node: GraphNode) =>
  Math.min(22, 7 + Math.sqrt(node.degree) * 1.6)

export const clip = (name: string | null) =>
  !name ? '' : name.length > 24 ? `${name.slice(0, 23)}…` : name

/* ── what is on screen ─────────────────────────────────────────────── */

/**
 * Add an expansion's nodes, edges and truncations to the current graph.
 * Existing nodes keep their depth; `root` stays the original seed.  The
 * expansion's truncations replace every earlier one for the node it
 * expanded, since the server lists only groups still cut: a group it now
 * sends whole has no entry, and an old one would claim edges are missing.
 */
export function merge(current: Neighbourhood,
                      more: Neighbourhood): Neighbourhood {
  const nodes = new Map(current.nodes.map((node) => [node.uid, node]))
  for (const node of more.nodes) if (!nodes.has(node.uid)) nodes.set(node.uid, node)
  const edges = new Map(current.edges.map((edge) => [edge.uid, edge]))
  for (const edge of more.edges) edges.set(edge.uid, edge)
  // The newer truncation entry for a group replaces the older one.
  const truncated = new Map(
    current.truncated
      .filter((t) => t.uid !== more.root)
      .map((t) => [`${t.uid}|${t.type}|${t.direction}`, t]))
  for (const t of more.truncated) {
    truncated.set(`${t.uid}|${t.type}|${t.direction}`, t)
  }
  return {
    root: current.root,
    nodes: [...nodes.values()],
    edges: [...edges.values()],
    truncated: [...truncated.values()],
  }
}

const LABEL_LIMIT = 5

/** The selected node's edges, if there are at most `LABEL_LIMIT`. */
export function labelled(graph: Neighbourhood,
                         selected: string | null): GraphEdge[] {
  if (!selected) return []
  const incident = graph.edges.filter(
    (edge) => edge.source === selected || edge.target === selected)
  return incident.length <= LABEL_LIMIT ? incident : []
}

/** Per (type, direction): edges drawn and total in the graph, largest first. */
export function connections(graph: Neighbourhood, uid: string) {
  const counts = new Map<string, { type: string; out: boolean; drawn: number }>()
  for (const edge of graph.edges) {
    const out = edge.source === uid
    if (!out && edge.target !== uid) continue
    const key = `${edge.type}|${out}`
    const seen = counts.get(key)
    if (seen) seen.drawn += 1
    else counts.set(key, { type: edge.type, out, drawn: 1 })
  }
  return [...counts.values()]
    .map((group) => ({
      ...group,
      total: graph.truncated.find(
        (cut) => cut.uid === uid && cut.type === group.type
              && cut.direction === (group.out ? 'out' : 'in'))?.total
        ?? group.drawn,
    }))
    .sort((a, b) => b.total - a.total)
}

/** Edges the server counted on this node but did not send. */
export function countHidden(graph: Neighbourhood, uid: string): number {
  return graph.truncated
    .filter((t) => t.uid === uid)
    .reduce((total, t) => total + (t.total - t.shown), 0)
}
