"""
A bounded neighbourhood of one node, for the graph view and ``explore_srd_graph``.

Bounded by ``depth`` hops, ``fan`` neighbours per (node, type, direction)
group, and ``limit`` nodes; ``truncated`` reports what the caps cut.  Nodes
are addressed by ``elementId``, since derived nodes have no section id; it is
stable until the next load.
"""

from __future__ import annotations

import re
from typing import Any

from .retrieval import query

_MARKUP = re.compile(r"[*_`]{1,3}|^#+\s*", re.M)

_TABLE_ROW = re.compile(r"^\s*\|.*$", re.M)

# Shorter summaries are dropped in favour of facts.
MIN_SUMMARY = 20

# A short line with no sentence end; dropped only when a table row follows,
# since stat blocks open with short lines like "Medium Undead, Neutral evil".
_STRANDED = re.compile(r"^[^.!?]{0,30}$")

FAN = 8
LIMIT = 60
MAX_DEPTH = 3

_UNINFORMATIVE = {"Section"}

# Full content for 60 nodes would be about a megabyte.
SUMMARY_CHARS = 260

# Keys, ids and fields the card already shows elsewhere.
_NOT_A_FACT = {
    "name", "key", "id", "heading", "content", "description", "depth",
    "entity_type", "char_start", "char_end", "page_start", "page_end",
    "section_id", "parent_class", "owner", "creature", "term_type",
    # Duplicates of the label and of ``cost``.
    "kind", "cost_gp",
}

FACT_CHARS = 120

# Excluded from ``facts``; long prose arrives once, as ``summary``.
BULKY = ["content", "description", "preamble", "entries_json",
         "outcomes_json"]

_SEED_BY_SECTION = "MATCH (n:Section {id: $key})"
_SEED_BY_NODE = "MATCH (n) WHERE elementId(n) = $key"

# Sections have ``content``, derived nodes ``description``.  ``facts`` are
# all other properties, as key/value pairs.
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

# One row per sampled edge.  Each (type, direction) group is sliced to
# ``$fan`` separately, taking the highest-degree neighbours with name as the
# tie-break, so samples are deterministic.  Alphabetical sampling showed
# only leaves (e.g. Rules Definitions' first eight subsections).
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
    """
    Plain-text opening of a passage for the details card.

    Args:
        text: Markdown content.

    Returns:
        Markdown and table rows stripped, cut at a word near
        ``SUMMARY_CHARS``; None if under ``MIN_SUMMARY`` characters remain.
    """
    if not text:
        return None
    text = " ".join(_prose(_MARKUP.sub("", text).splitlines()))
    if len(text) < MIN_SUMMARY:
        return None
    if len(text) <= SUMMARY_CHARS:
        return text
    return text[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


def _prose(lines: list[str]) -> list[str]:
    """Non-blank lines minus table rows and the column headings above them."""
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
    Up to six displayable properties, for nodes without prose (e.g. a Dagger).

    Args:
        pairs: ``[key, value]`` pairs from the query.

    Returns:
        ``{"name", "value"}`` dicts, sorted by key.
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
    Rejoin ``resource_names``/``resource_values`` as ``resources``,
    e.g. ``["Rages 3", "Rage Damage +2"]``.
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
    The ``creature`` property, if present.  Disambiguates abilities that
    share a name (the book prints a dozen "Swallow"s).
    """
    for pair in pairs or []:
        if len(pair) == 2 and pair[0] == "creature":
            return str(pair[1])
    return None


def _node(row: dict, depth: int) -> dict:
    """A query row as the node dict the UI draws."""
    labels = [l for l in row["labels"] or [] if l not in _UNINFORMATIVE]
    summary = _summarise(row.get("summary"))
    return {
        "uid": row["uid"],
        "name": row["name"],
        "labels": labels,
        "entity_type": row["entity_type"],
        # Facts only without a summary; a creature has forty properties.
        "summary": summary,
        "facts": [] if summary else _facts(row.get("facts")),
        "owner": _owner(row.get("facts")),
        # None on derived nodes, which therefore have no page to open.
        "section_id": row["section_id"],
        "page": row["page"],
        "degree": row["degree"],
        "depth": depth,
    }


def assemble(seed: dict, rounds: list[list[dict]], limit: int) -> dict:
    """
    Fold per-hop ``_NEIGHBOURS`` rows into a graph within a node budget.

    Nodes are admitted in discovery order until ``limit``.  Edges to a node
    that was not admitted, and rows anchored at one, are dropped.  A node
    keeps the depth it was first reached at.

    Args:
        seed: The seed node's row.
        rounds: ``_NEIGHBOURS`` rows per hop.
        limit: Maximum nodes, the seed included.

    Returns:
        ``root``, ``nodes``, ``edges``, and ``truncated``: each group where
        fewer edges were drawn than exist, with ``total`` and ``shown``.
    """
    nodes: dict[str, dict] = {seed["uid"]: _node(seed, 0)}
    edges: dict[str, dict] = {}
    # (anchor uid, type, outgoing) -> total edges in the database.
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
    The bounded graph around one node.

    Args:
        section_id: Seed by dotted section id.
        uid: Seed by ``elementId``.  Exactly one of the two is required.
        depth: Hops, clamped to ``0..MAX_DEPTH``.
        fan: Neighbours per (node, type, direction) group.
        limit: Maximum nodes.

    Returns:
        See ``assemble``; None if the seed does not exist.

    Raises:
        ValueError: Neither or both of ``section_id`` and ``uid`` given.
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
