"""
One node and what surrounds it, for the graph explorer.

Where ``retrieval`` reads the graph for prose to cite, this reads it for
shape: a seed node, its neighbours and the edges between them.

The result is bounded three ways, because a hub is enormous —
``:DamageType {name: 'Poison'}`` alone has 195 edges: ``depth`` hops from the
seed, ``fan`` neighbours per relationship type per direction per node, and
``limit`` nodes in total.  What the caps cut is counted in ``truncated``
rather than dropped in silence.

Nodes are addressed by ``elementId``.  A citation names a section, but the
neighbours are not all sections — an ability is keyed on ``key``, a damage
type on ``name`` — so there is no one property to address them all by.  The
element id is stable for the life of a load, which is the life of anything
looking at it.
"""

from __future__ import annotations

import re
from typing import Any

from .retrieval import query

# Emphasis and heading markers, which are the book's typography rather than
# its words.
_MARKUP = re.compile(r"[*_`]{1,3}|^#+\s*", re.M)

# A markdown table row.  A table read as a sentence is not a summary of
# anything — the Mysterious Deck's content is a hundred-row draw table, and
# flattened it begins "1d100 1d100 | (13-Card | (22-Card | Card | |---|---|".
_TABLE_ROW = re.compile(r"^\s*\|.*$", re.M)

# Below this there is nothing left worth showing, and the facts are better.
MIN_SUMMARY = 20

# A table's column headings are emitted as their own short paragraphs above
# it, so cutting the rows leaves "1d100 1d100" stranded at the front of the
# Mysterious Deck. What identifies one is not that it is short — a stat
# block opens with "Medium Undead, Neutral evil", which is short and is the
# most useful line it has — but that a table follows it.
_STRANDED = re.compile(r"^[^.!?]{0,30}$")

# Defaults the route exposes as parameters: how much is too much depends on
# the screen it is drawn on.
FAN = 8
LIMIT = 60
MAX_DEPTH = 3

# ``:Section`` is on 2368 nodes and says nothing about which one this is.
_UNINFORMATIVE = {"Section"}

# Enough prose to recognise a passage by, not to read it: sixty nodes of
# full ``content`` would be a megabyte of payload for a picture.
SUMMARY_CHARS = 260

# Properties that are structure rather than substance: keys and ids, and the
# fields the card already shows above the fact list.
_NOT_A_FACT = {
    "name", "key", "id", "heading", "content", "description", "depth",
    "entity_type", "char_start", "char_end", "page_start", "page_end",
    "section_id", "parent_class", "owner", "creature", "term_type",
    # Redundant rather than structural: ``kind`` repeats the label, and
    # ``cost_gp`` is ``cost`` again as a number for sorting by.
    "kind", "cost_gp",
}

# A fact is a line in a small card, not a paragraph.  The Rogue's starting
# equipment is 180 characters of either/or.
FACT_CHARS = 120

# Fetched as ``summary`` or not at all; a stat block's prose is thousands of
# characters and would otherwise cross the wire twice for every node.
BULKY = ["content", "description", "preamble", "entries_json",
         "outcomes_json"]

_SEED_BY_SECTION = "MATCH (n:Section {id: $key})"
_SEED_BY_NODE = "MATCH (n) WHERE elementId(n) = $key"

# ``content`` on a node that is a section, ``description`` on one the loader
# derived; between them, every node with prose.  ``facts`` is what a node
# shows when that prose is missing or turns out to be a table, fetched as
# key/value pairs with the bulky text fields excluded so a stat block's
# ``content`` does not cross the wire twice per row.
_SUBSTANCE = """
       left(coalesce({n}.content, {n}.description), 1200) AS summary,
       [k IN keys({n}) WHERE NOT k IN $bulky | [k, {n}[k]]] AS facts
"""

_RETURN_NODE = """
RETURN elementId(n) AS uid, labels(n) AS labels, n.entity_type AS entity_type,
       coalesce(n.heading, n.name, n.key, n.id) AS name,
       n.id AS section_id, n.page_start AS page,
       COUNT { (n)--() } AS degree,
""" + _SUBSTANCE.format(n="n")

# One row per edge, carrying the group it was sampled from.  The subquery
# groups by type *and* direction and slices each group, so a node with 121
# incoming references and one outgoing definition returns 8 of the first and
# all of the second, rather than 8 rows that all happen to be references.
#
# The slice takes the *best connected* of each group, not the first
# alphabetically.  Rules Definitions has 155 subsections; sampled by name it
# is always the same eight entries beginning with A, each of them a leaf,
# and the picture says nothing.  Sampled by degree it reaches the parts of
# the book everything else points at, which is the question a graph view is
# being asked.  The name breaks ties, so the sample stays deterministic and
# a second identical request returns the same nodes.
_NEIGHBOURS = """
MATCH (n) WHERE elementId(n) IN $uids
CALL (n) {
  MATCH (n)-[rel]-(m)
  WITH type(rel) AS type, startNode(rel) = n AS outgoing, rel, m,
       COUNT { (m)--() } AS degree
  ORDER BY degree DESC, coalesce(m.heading, m.name, m.key, m.id)
  WITH type, outgoing, collect({rel: rel, other: m}) AS group
  RETURN type, outgoing, size(group) AS total, group[0..$fan] AS shown
}
UNWIND shown AS hit
WITH n, type, outgoing, total, hit.rel AS rel, hit.other AS m
RETURN elementId(n) AS anchor, type, outgoing, total,
       elementId(rel) AS edge,
       elementId(m) AS uid, labels(m) AS labels, m.entity_type AS entity_type,
       coalesce(m.heading, m.name, m.key, m.id) AS name,
       m.id AS section_id, m.page_start AS page,
       COUNT { (m)--() } AS degree,
""" + _SUBSTANCE.format(n="m") + """
ORDER BY anchor, type, outgoing, name
"""


def _summarise(text: str | None) -> str | None:
    """The opening of a passage, cut at a word rather than mid-syllable."""
    if not text:
        return None
    # The content is markdown and the card shows plain text, so the book's
    # own emphasis would arrive as "**_Restricted Movement._**" mid-sentence.
    text = " ".join(_prose(_MARKUP.sub("", text).splitlines()))
    # A section that is only a table has no prose to summarise; returning
    # nothing lets the facts take the space instead.
    if len(text) < MIN_SUMMARY:
        return None
    if len(text) <= SUMMARY_CHARS:
        return text
    return text[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


def _prose(lines: list[str]) -> list[str]:
    """Drop the table rows, and the headings orphaned by dropping them."""
    kept = []
    for index, line in enumerate(lines):
        line = line.strip()
        if not line or _TABLE_ROW.match(line):
            continue
        following = next((later.strip() for later in lines[index + 1:]
                          if later.strip()), "")
        if _STRANDED.match(line) and _TABLE_ROW.match(following):
            continue
        kept.append(line)
    return kept


def _facts(pairs: list[list] | None) -> list[dict]:
    """
    What to show for a node with no prose at all.

    A Dagger is a table row — a cost, a die and a weight, and not one
    sentence in the book — so listing what it carries beats an empty card.
    """
    if not pairs:
        return []
    properties = _pair_resources({key: value for key, value in pairs})
    facts = []
    for key in sorted(properties):
        value = properties[key]
        if key in _NOT_A_FACT or key.endswith("_json") or value in (None, "", []):
            continue
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)
        value = " ".join(str(value).split())
        if len(value) > FACT_CHARS:
            value = value[:FACT_CHARS].rsplit(" ", 1)[0] + "…"
        facts.append({"name": key.replace("_", " "), "value": value})
    return facts[:6]


def _pair_resources(properties: dict) -> dict:
    """
    Put a class level's resources back together.

    The mapper splits a ``resources`` map into ``resource_names`` and
    ``resource_values``, corresponding by position, because Neo4j stores no
    nested maps.  Side by side the two lists read as noise; recombined,
    "Rages 3, Rage Damage +2" reads as the table row it came from.
    """
    names = properties.get("resource_names")
    values = properties.get("resource_values")
    if not isinstance(names, list) or not isinstance(values, list):
        return properties
    paired = dict(properties)
    paired.pop("resource_names")
    paired.pop("resource_values")
    paired["resources"] = [f"{name} {value}"
                           for name, value in zip(names, values)]
    return paired


def _owner(pairs: list[list] | None) -> str | None:
    """
    The creature an ability belongs to, which is the only thing that tells
    two of them apart.

    ``:CreatureAbility`` is named for the entry — "Swallow", "Bite" — and the
    book prints a dozen of each.  The name alone is not an answer to "which
    creatures can do this"; the name with its owner is.
    """
    for pair in pairs or []:
        if len(pair) == 2 and pair[0] == "creature":
            return str(pair[1])
    return None


def _node(row: dict, depth: int) -> dict:
    """One node as the UI draws it: a name, what it is, and how big it is."""
    labels = [l for l in row["labels"] or [] if l not in _UNINFORMATIVE]
    summary = _summarise(row.get("summary"))
    return {
        "uid": row["uid"],
        "name": row["name"],
        "labels": labels,
        "entity_type": row["entity_type"],
        # Arrives with the node, so selecting one costs no request.  Facts
        # ride along only when there is no summary to show instead — a
        # creature has forty properties and never needs them.
        "summary": summary,
        "facts": [] if summary else _facts(row.get("facts")),
        # Named separately from the facts, which a node with prose does not
        # carry: without it two abilities called "Swallow" are the same line
        # twice.
        "owner": _owner(row.get("facts")),
        # Present only on nodes that *are* a section, which is what decides
        # whether the Page tab can open on this node at all.
        "section_id": row["section_id"],
        "page": row["page"],
        "degree": row["degree"],
        "depth": depth,
    }


def assemble(seed: dict, rounds: list[list[dict]], limit: int) -> dict:
    """
    Rows from ``_NEIGHBOURS``, one list per hop, folded into a drawable graph.

    Pure, so the budget arithmetic is testable without a database.

    The budget is spent in discovery order, and an edge whose far end did not
    fit is dropped with it — an edge to a node that was never returned draws
    as a line into nothing, which is also why a row anchored at a node the
    budget refused is skipped.  A node reached twice keeps the shallower
    depth.  A group counts as truncated only when fewer edges were drawn from
    it than the database counted, so a cap that cut nothing says nothing.
    """
    nodes: dict[str, dict] = {seed["uid"]: _node(seed, 0)}
    edges: dict[str, dict] = {}
    # Keyed by the group the fan cap applied to — one node, one relationship
    # type, one direction — so a group is never reported twice.
    groups: dict[tuple[str, str, bool], int] = {}

    for depth, rows in enumerate(rounds, start=1):
        for row in rows:
            if row["anchor"] not in nodes:
                continue
            groups[(row["anchor"], row["type"], row["outgoing"])] = row["total"]
            if row["uid"] not in nodes:
                if len(nodes) >= limit:
                    continue
                nodes[row["uid"]] = _node(row, depth)
            edges.setdefault(row["edge"], {
                "uid": row["edge"],
                "type": row["type"],
                "source": row["anchor"] if row["outgoing"] else row["uid"],
                "target": row["uid"] if row["outgoing"] else row["anchor"],
            })

    drawn: dict[tuple[str, str, bool], int] = {}
    for edge in edges.values():
        for uid, outgoing in ((edge["source"], True), (edge["target"], False)):
            key = (uid, edge["type"], outgoing)
            if key in groups:
                drawn[key] = drawn.get(key, 0) + 1

    return {
        "root": seed["uid"],
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "truncated": [
            {"uid": uid, "type": type_,
             "direction": "out" if outgoing else "in",
             "total": total, "shown": drawn.get((uid, type_, outgoing), 0)}
            for (uid, type_, outgoing), total in groups.items()
            if total > drawn.get((uid, type_, outgoing), 0)
        ],
    }


def neighbourhood(*, section_id: str | None = None, uid: str | None = None,
                  depth: int = 1, fan: int = FAN,
                  limit: int = LIMIT) -> dict | None:
    """
    The graph around one node, ``depth`` hops out and bounded on every side.

    Exactly one of ``section_id`` (how a citation gets in) and ``uid`` (how
    an already-drawn node expands) identifies the seed.  ``None`` when there
    is no such node, as ``get_section`` returns for an id that resolves to
    nothing.
    """
    if (section_id is None) == (uid is None):
        raise ValueError("neighbourhood takes exactly one of section_id, uid")

    key = section_id if section_id is not None else uid
    match = _SEED_BY_SECTION if section_id is not None else _SEED_BY_NODE
    found = query(match + _RETURN_NODE, {"key": key, "bulky": BULKY})
    if not found:
        return None

    depth = max(0, min(depth, MAX_DEPTH))
    rounds: list[list[dict]] = []
    seen = {found[0]["uid"]}
    frontier = [found[0]["uid"]]
    for _ in range(depth):
        rows = query(_NEIGHBOURS, {"uids": frontier, "fan": fan,
                                   "bulky": BULKY})
        rounds.append(rows)
        frontier = [row["uid"] for row in rows if row["uid"] not in seen]
        seen.update(frontier)
        if not frontier:
            break

    return assemble(found[0], rounds, limit)
