import { describe, expect, it } from 'vitest'

import type { GraphEdge, GraphNode, Neighbourhood } from '../../api'
import {
  clip, connections, countHidden, fit, kindOf, labelled, merge, radiusOf,
  restLength,
} from './graph-layout'

const node = (uid: string, overrides: Partial<GraphNode> = {}): GraphNode => ({
  uid, name: uid, labels: ['Rule'], entity_type: 'rule',
  section_id: uid, page: 1, summary: null, facts: [], degree: 3, depth: 1,
  ...overrides,
})

const edge = (uid: string, source: string, target: string,
              type = 'HAS_SUBSECTION'): GraphEdge => ({ uid, type, source, target })

const graph = (overrides: Partial<Neighbourhood> = {}): Neighbourhood => ({
  root: 'root',
  nodes: [node('root', { name: 'Prone [Condition]', labels: ['Condition'],
                          depth: 0 }),
          node('a', { name: 'Grappled' })],
  edges: [edge('e1', 'root', 'a')],
  truncated: [],
  ...overrides,
})

const body = (x: number, y: number) => ({ x, y, vx: 0, vy: 0, pinned: false })

describe('kindOf', () => {
  it('given a multi-label node, when coloured, then the most specific wins', () => {
    // Given a node carrying several labels at once
    const poison = node('p', { labels: ['Rule', 'Equipment', 'Poison'] })

    // When its kind is decided
    // Then the specific label decides, not the order they arrived in
    expect(kindOf(poison)).toBe('item')
  })

  it('given a creature, when coloured, then it is drawn as one', () => {
    // Given a creature node
    // When its kind is decided
    // Then it takes the creature colour
    expect(kindOf(node('c', { labels: ['Creature'] }))).toBe('creature')
  })

  it('given a label the palette does not know, when coloured, then it falls back', () => {
    /**
     * An unlisted label draws grey without error; test_docs.py checks this
     * table against the mapper.
     */
    // Given a node with no known label
    // When its kind is decided
    // Then it is drawn as a bare section
    expect(kindOf(node('x', { labels: ['Newish'] }))).toBe('section')
  })
})

describe('radiusOf', () => {
  it('given a better-connected node, when sized, then it is drawn bigger', () => {
    // Given a leaf and a hub
    // When both are sized
    // Then the busier node reads as busier
    expect(radiusOf(node('a', { degree: 100 })))
      .toBeGreaterThan(radiusOf(node('b', { degree: 2 })))
  })

  it('given a hub of any size, when sized, then it stops growing', () => {
    // Given an enormous hub
    // When it is sized
    // Then the radius is capped
    expect(radiusOf(node('a', { degree: 10000 }))).toBe(22)
  })
})

describe('restLength', () => {
  it('given few nodes in a large panel, when spaced, then the spring is capped', () => {
    // Given two nodes on a big canvas
    // When the rest length is derived
    // Then it stops at the maximum rather than filling the panel
    expect(restLength({ width: 1200, height: 900 }, 2)).toBe(280)
  })

  it('given many nodes in a small panel, when spaced, then it has a floor', () => {
    // Given a crowded canvas
    // When the rest length is derived
    // Then it stops at the minimum
    expect(restLength({ width: 400, height: 300 }, 60)).toBe(92)
  })

  it('given the same panel, when it holds more nodes, then they settle closer', () => {
    // Given one canvas holding two different graphs
    const roomy = restLength({ width: 900, height: 700 }, 12)
    const crowded = restLength({ width: 900, height: 700 }, 40)

    // When the two are compared
    // Then more nodes means shorter edges
    expect(roomy).toBeGreaterThan(crowded)
  })
})

describe('fit', () => {
  it('given no nodes at all, when fitted, then the view is neutral', () => {
    // Given nothing laid out
    // When it is fitted
    // Then the camera does not divide by an empty picture
    expect(fit([], { width: 800, height: 600 }, 0)).toEqual({ x: 0, y: 0, k: 1 })
  })

  it('given a crowded picture, when fitted, then it stops shrinking at the floor', () => {
    // Given a wide spread of nodes in a small panel
    const spread = Array.from({ length: 30 }, (_, i) => body(i * 200, 0))

    // When it is fitted
    const view = fit(spread, { width: 500, height: 400 }, 0)

    // Then the picture overflows rather than shrinking past readable
    expect(view.k).toBe(1)
  })

  it('given a tiny picture, when fitted, then it stops growing at the ceiling', () => {
    // Given two nodes close together in a large panel
    // When they are fitted
    const view = fit([body(0, 0), body(10, 0)], { width: 1200, height: 900 }, 0)

    // Then the magnification is bounded
    expect(view.k).toBe(1.5)
  })

  it('given the details card, when fitted, then the space it covers is not laid out in', () => {
    // Given the same picture fitted with and without a card over it
    const points = [body(-300, -200), body(300, 200)]
    const whole = fit(points, { width: 900, height: 800 }, 0)
    const around = fit(points, { width: 900, height: 800 }, 300)

    // When the two are compared
    // Then the card's height moved the picture up out from under it
    expect(around.y).toBeLessThan(whole.y)
  })
})

describe('merge', () => {
  it('given an expansion, when merged, then it grows the picture already drawn', () => {
    // Given a drawn graph and an expansion of one of its nodes
    const drawn = graph()
    const more: Neighbourhood = {
      root: 'a', nodes: [node('b')], edges: [edge('e2', 'a', 'b')],
      truncated: [],
    }

    // When the two are merged
    const merged = merge(drawn, more)

    // Then the seed is still the citation the reader arrived on
    expect(merged.root).toBe('root')
    expect(merged.nodes.map((n) => n.uid)).toEqual(['root', 'a', 'b'])
  })

  it('given a node reached again, when merged, then it keeps the depth it was drawn at', () => {
    // Given a node already drawn one hop out
    const drawn = graph()
    const more: Neighbourhood = {
      root: 'a', nodes: [node('a', { depth: 5 })], edges: [], truncated: [],
    }

    // When the expansion is merged
    const merged = merge(drawn, more)

    // Then it is not redrawn further away than it is
    expect(merged.nodes.find((n) => n.uid === 'a')?.depth).toBe(1)
  })

  it('given a group sampled again, when merged, then the later count wins', () => {
    // Given a truncation reported before and after an expansion
    const drawn = graph({
      truncated: [{ uid: 'a', type: 'REFERENCES_SPELL', direction: 'out',
                    total: 121, shown: 8 }] })
    const more: Neighbourhood = {
      root: 'a', nodes: [], edges: [],
      truncated: [{ uid: 'a', type: 'REFERENCES_SPELL', direction: 'out',
                    total: 121, shown: 16 }] }

    // When they are merged
    const merged = merge(drawn, more)

    // Then one row is kept, saying what is actually on screen
    expect(merged.truncated).toEqual([
      { uid: 'a', type: 'REFERENCES_SPELL', direction: 'out', total: 121,
        shown: 16 }])
  })

  it('given a group fetched whole, when merged, then it is no longer cut', () => {
    // Given a group cut before, and an expansion that drew all of it, which
    // the server reports by leaving the group out of `truncated`
    const drawn = graph({
      truncated: [{ uid: 'a', type: 'REFERENCES_SPELL', direction: 'out',
                    total: 9, shown: 8 }] })
    const more: Neighbourhood = { root: 'a', nodes: [], edges: [],
                                  truncated: [] }

    // When they are merged
    const merged = merge(drawn, more)

    // Then nothing claims edges are still missing
    expect(merged.truncated).toEqual([])
  })

  it('given another node cut, when one is expanded, then the other stays cut', () => {
    // Given two nodes cut, and an expansion of only one of them
    const other = { uid: 'root', type: 'HAS_SUBSECTION', direction: 'out' as const,
                    total: 30, shown: 8 }
    const drawn = graph({
      truncated: [other, { uid: 'a', type: 'REFERENCES_SPELL', direction: 'out',
                           total: 9, shown: 8 }] })
    const more: Neighbourhood = { root: 'a', nodes: [], edges: [],
                                  truncated: [] }

    // When they are merged
    // Then only the expanded node's count is replaced
    expect(merge(drawn, more).truncated).toEqual([other])
  })

  it('given an edge already drawn, when merged, then it is not duplicated', () => {
    // Given an expansion repeating an edge
    const drawn = graph()
    const more: Neighbourhood = { root: 'a', nodes: [],
                                  edges: [edge('e1', 'root', 'a')],
                                  truncated: [] }

    // When they are merged
    // Then the picture holds one line, not two on top of each other
    expect(merge(drawn, more).edges).toHaveLength(1)
  })
})

describe('labelled', () => {
  it('given nothing selected, when labelled, then no edge is written on', () => {
    // Given a graph with no selection
    // When the labels are chosen
    // Then the picture stays quiet
    expect(labelled(graph(), null)).toEqual([])
  })

  it('given a selected node, when labelled, then its own edges are named', () => {
    // Given a selected node with one edge
    // When the labels are chosen
    const written = labelled(graph(), 'root')

    // Then that edge carries its relationship
    expect(written.map((e) => e.uid)).toEqual(['e1'])
  })

  it('given more edges than can be read, when labelled, then none is written', () => {
    // Given a node with six edges
    const busy = graph({
      nodes: [node('root'), ...'abcdef'.split('').map((n) => node(n))],
      edges: 'abcdef'.split('').map((n, i) => edge(`e${i}`, 'root', n)),
    })

    // When the labels are chosen
    // Then the count in the card is left to say it instead
    expect(labelled(busy, 'root')).toEqual([])
  })
})

describe('connections', () => {
  it('given a node, when counted, then each relationship and direction is its own row', () => {
    // Given a node with edges in both directions
    const both = graph({
      nodes: [node('root'), node('a'), node('b')],
      edges: [edge('e1', 'root', 'a', 'HAS_SUBSECTION'),
              edge('e2', 'b', 'root', 'REFERENCES_CONDITION')],
    })

    // When its connections are counted
    const rows = connections(both, 'root')

    // Then the two are not conflated
    expect(rows).toHaveLength(2)
    expect(rows.map((row) => row.out).sort()).toEqual([false, true])
  })

  it('given a truncated group, when counted, then the row says how many exist', () => {
    // Given a group the server sampled
    const hub = graph({
      truncated: [{ uid: 'root', type: 'HAS_SUBSECTION', direction: 'out',
                    total: 121, shown: 1 }] })

    // When the connections are counted
    const [row] = connections(hub, 'root')

    // Then the row carries both what is drawn and what there is
    expect(row).toMatchObject({ drawn: 1, total: 121 })
  })

  it('given nothing cut, when counted, then the total is what is drawn', () => {
    // Given a group returned whole
    // When the connections are counted
    const [row] = connections(graph(), 'root')

    // Then no larger number is implied
    expect(row).toMatchObject({ drawn: 1, total: 1 })
  })

  it('given several groups, when counted, then the biggest leads', () => {
    // Given two relationship types of different sizes
    const many = graph({
      nodes: [node('root'), node('a'), node('b')],
      edges: [edge('e1', 'root', 'a', 'SMALL'),
              edge('e2', 'root', 'b', 'BIG')],
      truncated: [{ uid: 'root', type: 'BIG', direction: 'out', total: 90,
                    shown: 1 }],
    })

    // When the connections are counted
    // Then the row that says the most is first
    expect(connections(many, 'root')[0].type).toBe('BIG')
  })
})

describe('countHidden', () => {
  it('given a sampled node, when counted, then the difference is what is hidden', () => {
    // Given two groups the server cut
    const hub = graph({
      truncated: [
        { uid: 'root', type: 'A', direction: 'out', total: 121, shown: 8 },
        { uid: 'root', type: 'B', direction: 'in', total: 10, shown: 4 },
      ] })

    // When the hidden edges are counted
    // Then it is what was counted less what was sent
    expect(countHidden(hub, 'root')).toBe(119)
  })

  it('given a node returned whole, when counted, then nothing is hidden', () => {
    // Given a node with no truncation against it
    // When the hidden edges are counted
    // Then there is nothing to expand for
    expect(countHidden(graph(), 'root')).toBe(0)
  })
})

describe('clip', () => {
  it('given a long name, when clipped, then it is cut with an ellipsis', () => {
    // Given a name longer than a label can carry
    // When it is clipped
    // Then it stops at the width the fit is calculated for
    expect(clip('Antimagic Susceptibility and More Besides'))
      .toBe('Antimagic Susceptibilit…')
  })

  it('given a short name, when clipped, then it is untouched', () => {
    // Given a name that fits
    // When it is clipped
    // Then nothing is taken off it
    expect(clip('Prone')).toBe('Prone')
  })

  it('given no name at all, when clipped, then the label is empty', () => {
    // Given a node with no name
    // When it is clipped
    // Then it draws nothing rather than "null"
    expect(clip(null)).toBe('')
  })
})
