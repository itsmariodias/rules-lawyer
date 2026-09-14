/**
 * The arithmetic behind the graph explorer, with no React in it.
 *
 * `GraphView.tsx` draws the picture; this decides its shape — how far apart
 * two joined nodes settle, what transform puts the whole thing on screen,
 * which of a node's labels gives it its colour, and how an expansion folds
 * into what is already drawn.
 *
 * Separate from the view because none of it needs one: every function here
 * is a pure function of a neighbourhood, a size or a node, which is what
 * lets the layout be held to account without mounting a canvas.
 */

import type { GraphEdge, GraphNode, Neighbourhood } from '../api'

/** What the simulation works on. Velocity is its business, not the view's. */
export type Body = { x: number; y: number; vx: number; vy: number
                     pinned: boolean }

/** What the view draws: one published position per node, per frame. */
export type Places = Record<string, { x: number; y: number }>

/** Pan and zoom, in one place because fitting sets all three at once. */
export type View = { x: number; y: number; k: number }

/** The panel the picture is laid out in. */
export type Size = { width: number; height: number }

/* ── the spring ────────────────────────────────────────────────────── */

const REST_MIN = 92
const REST_MAX = 280

/**
 * How far apart two joined nodes settle: enough of the panel each that the
 * picture fills it, within bounds that keep a two-node graph from flinging
 * itself into the corners and a sixty-node one from overlapping itself.
 *
 * The rest length is not a constant: twelve nodes in a tall panel and sixty
 * in a short one want very different pictures, and a fixed length gives the
 * first a knot in the middle of an empty page. Sizing the layout is better
 * than magnifying it afterwards — zoom scales the circles and the type along
 * with the distances, and a graph blown up to fill a panel is just a graph
 * with enormous labels.
 */
export function restLength(size: Size, nodes: number): number {
  const each = Math.sqrt((size.width * size.height) / Math.max(nodes, 2))
  return Math.max(REST_MIN, Math.min(REST_MAX, each * 0.75))
}

/* ── fitting ───────────────────────────────────────────────────────── */

/**
 * Room around the picture, and the bounds fitting works between.
 *
 * Fitting has a *floor* as well as a ceiling, and the floor is the
 * interesting one: a node is not a dot, it is a dot with a name beside it
 * about 130 units wide, and thirty of those do not fit across a panel
 * whatever the spacing. Below `FIT_MIN` the picture stops shrinking and
 * overflows instead, to be panned — legible and partly off-screen beats
 * complete and unreadable. It is also why simply lengthening the edges does
 * not decrowd anything on its own: fitting scales the labels down with the
 * distances, and the two cancel.
 */
const MARGIN = 54
const FIT_MIN = 1
const FIT_MAX = 1.5

/**
 * How far a node's name reaches past the node itself, in layout units.
 *
 * The bounds are the *dots*, but what runs off the edge is a name centred
 * under one — `clip` caps it at 24 characters, so roughly this much either
 * side and a line and a half below.
 */
const LABEL = [64, 20] as const

/**
 * The transform that puts the whole picture on screen.
 *
 * A neighbourhood is three nodes or sixty depending on what was cited, and
 * a fixed zoom makes one of those a speck in an empty panel and the other a
 * knot running off both edges. So the view is derived from what is actually
 * laid out, between `FIT_MIN` and `FIT_MAX` — a two-node graph blown up to
 * fill a panel looks broken rather than close, and a sixty-node one shrunk
 * to fit is a diagram nobody can read.
 */
export function fit(points: Body[], size: Size, bottom: number): View {
  if (points.length === 0) return { x: 0, y: 0, k: 1 }
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  const left = Math.min(...xs) - LABEL[0]
  const right = Math.max(...xs) + LABEL[0]
  const high = Math.min(...ys)
  const low = Math.max(...ys) + LABEL[1]
  // The details card floats over the picture, so the space it covers is not
  // space to lay out in: fitting into the whole canvas puts the two or three
  // furthest nodes behind the card, where they are drawn and invisible.
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
 * Which of a node's labels decides how it is drawn.
 *
 * Nodes are multi-label by design — `:Section:Rule:Equipment:Poison` is one
 * real node — so a colour has to come from a priority, not from a lookup.
 * The order is most specific first: being a Poison says more about a node
 * than being Equipment does.
 *
 * A label missing from this table is not an error anywhere — the node simply
 * draws grey — so `backend/tests/test_docs.py` reads the table out of this
 * file and holds it against the mapper.
 */
export const KINDS: [string, string[]][] = [
  ['creature', ['Creature', 'CreatureGroup']],
  ['ability', ['CreatureAbility']],
  ['spell', ['Spell']],
  ['item', ['MagicItem', 'Weapon', 'Armor', 'Gear', 'Poison', 'Equipment',
            'EquipmentSection']],
  ['glossary', ['Condition', 'DamageType', 'PoisonType', 'Action',
                'AreaOfEffect', 'Hazard', 'Attitude', 'Definition',
                'GlossaryTerm', 'GlossarySection']],
  ['class', ['Class', 'Subclass', 'ClassLevel', 'ClassFeature', 'Feat',
             'FeatSection', 'Species', 'Background', 'Trait', 'Origin']],
  ['rule', ['Rule', 'Trap', 'EnvironmentalEffect', 'Contagion', 'FrontMatter']],
]

export function kindOf(node: GraphNode): string {
  for (const [kind, labels] of KINDS) {
    if (labels.some((label) => node.labels.includes(label))) return kind
  }
  return 'section'
}

/** Big nodes look big: the area grows with the degree, so it stays legible. */
export const radiusOf = (node: GraphNode) =>
  Math.min(22, 7 + Math.sqrt(node.degree) * 1.6)

export const clip = (name: string | null) =>
  !name ? '' : name.length > 24 ? `${name.slice(0, 23)}…` : name

/* ── what is on screen ─────────────────────────────────────────────── */

/**
 * Fold an expansion into the picture already on screen.
 *
 * Nodes and edges are keyed, so a node reached a second time is not
 * duplicated — and it keeps the depth it was first drawn at, which is the
 * distance from the citation the reader started at. `root` is the seed's,
 * never the expansion's: expanding is walking around one picture, not
 * opening another.
 */
export function merge(current: Neighbourhood,
                      more: Neighbourhood): Neighbourhood {
  const nodes = new Map(current.nodes.map((node) => [node.uid, node]))
  for (const node of more.nodes) if (!nodes.has(node.uid)) nodes.set(node.uid, node)
  const edges = new Map(current.edges.map((edge) => [edge.uid, edge]))
  for (const edge of more.edges) edges.set(edge.uid, edge)
  // A group the server sampled again is reported again; the later count is
  // the one that matches what is now drawn.
  const truncated = new Map(
    current.truncated.map((t) => [`${t.uid}|${t.type}|${t.direction}`, t]))
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

/**
 * The edges to write the type on.
 *
 * Only the selected node's, and only when there are few enough to read: a
 * section with ten subsections drew `has_subsection` ten times over itself
 * and said nothing the count in the details card does not say better.
 */
const LABEL_LIMIT = 5

export function labelled(graph: Neighbourhood,
                         selected: string | null): GraphEdge[] {
  if (!selected) return []
  const incident = graph.edges.filter(
    (edge) => edge.source === selected || edge.target === selected)
  return incident.length <= LABEL_LIMIT ? incident : []
}

/**
 * One line per kind of connection this node has: the relationship, which way
 * it points, how many are drawn and how many exist.
 *
 * This is where a hub becomes readable. The picture can honestly show eight
 * of Poison's 121 references; only a count can say that it is 121.
 */
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
