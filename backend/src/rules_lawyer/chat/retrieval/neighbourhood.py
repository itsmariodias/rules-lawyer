"""A bounded neighbourhood of one node, for the graph view and ``explore_srd_graph``.

Bounded by ``depth`` hops, ``fan`` neighbours per (node, type, direction)
group, and ``limit`` nodes; ``truncated`` reports what the caps cut.  Nodes
are addressed by ``elementId``, since derived nodes have no section id; it is
stable until the next load.

The section tree has 16 roots and nothing above them, so a walk with no seed
starts at ``BOOK``, a node made here and never stored, joined to every root.
"""

from __future__ import annotations

import re

from rules_lawyer.chat.retrieval.search import query

_MARKUP = re.compile(r"[*_`]{1,3}|^#+\s*", re.MULTILINE)

_TABLE_ROW = re.compile(r"^\s*\|.*$", re.MULTILINE)

# Shorter summaries are dropped in favour of facts.
MIN_SUMMARY = 20

# A short line with no sentence end; dropped only when a table row follows,
# since stat blocks open with short lines like "Medium Undead, Neutral evil".
_STRANDED = re.compile(r"^[^.!?]{0,30}$")

FAN = 8
LIMIT = 60
MAX_DEPTH = 3

_UNINFORMATIVE = {"Section"}

# Full content for `LIMIT` nodes would be about a megabyte.
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
BULKY = ["content", "description", "outcomes_json"]

# The virtual node's uid; Neo4j's element ids look like ``4:<uuid>:<n>``.
BOOK = "book"
BOOK_LABEL = "Book"
# The title every page footer prints (``meta.title``); the graph stores none.
BOOK_TITLE = "System Reference Document 5.2.1"

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

_ROOTS = ("MATCH (n:Section) WHERE NOT ()-[:HAS_SUBSECTION]->(n)"
          + _RETURN_NODE + "ORDER BY toInteger(n.id)")

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
    """Plain-text opening of a passage for the details card.

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
    """Up to six displayable properties, for nodes without prose (e.g. a Dagger).

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
    """Rejoin ``resource_names``/``resource_values`` as ``resources``,
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
    """The ``creature`` property, if present.  Disambiguates abilities that
    share a name (the book prints a dozen "Swallow"s).
    """
    for pair in pairs or []:
        if len(pair) == 2 and pair[0] == "creature":
            return str(pair[1])
    return None


def _node(row: dict, depth: int) -> dict:
    """A query row as the node dict the UI draws."""
    labels = [label for label in row["labels"] or []
              if label not in _UNINFORMATIVE]
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
    """Fold per-hop ``_NEIGHBOURS`` rows into a graph within a node budget.

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
    """The bounded graph around one node.

    Args:
        section_id: Seed by dotted section id.
        uid: Seed by ``elementId``, or ``BOOK``.  With neither seed, the walk
            starts at ``BOOK``, whose neighbours are the 16 root sections,
            all shown whatever ``fan`` is.
        depth: Hops, clamped to ``0..MAX_DEPTH``.
        fan: Neighbours per (node, type, direction) group.
        limit: Maximum nodes.

    Returns:
        See ``assemble``; None if the seed does not exist.

    Raises:
        ValueError: Both ``section_id`` and ``uid`` given.
    """
    if section_id is not None and uid is not None:
        raise ValueError("neighbourhood takes at most one of section_id, uid")

    depth = max(0, min(depth, MAX_DEPTH))
    if section_id is None and uid in (None, BOOK):
        return _book(depth, fan, limit)

    key = section_id if section_id is not None else uid
    match = _SEED_BY_SECTION if section_id is not None else _SEED_BY_NODE
    found = query(match + _RETURN_NODE, {"key": key, "bulky": BULKY})
    if not found:
        return None

    seed = found[0]["uid"]
    return assemble(found[0], _rounds([seed], {seed}, depth, fan), limit)


def _book(depth: int, fan: int, limit: int) -> dict:
    """The walk from ``BOOK``: the root sections, then ``depth - 1`` hops on."""
    roots = query(_ROOTS, {"bulky": BULKY})
    seed = {
        "uid": BOOK, "labels": [BOOK_LABEL], "entity_type": None,
        "name": BOOK_TITLE, "section_id": None, "page": None,
        "degree": len(roots), "summary": None, "facts": None,
    }
    if depth == 0:
        return assemble(seed, [], limit)
    # The roots as ``_NEIGHBOURS`` rows; their degree counts the book's edge.
    first = [{**row, "anchor": BOOK, "type": "HAS_SUBSECTION",
              "outgoing": True, "total": len(roots),
              "edge": f"{BOOK}:{row['uid']}", "degree": row["degree"] + 1}
             for row in roots]
    uids = [row["uid"] for row in roots]
    later = _rounds(uids, {BOOK, *uids}, depth - 1, fan)
    return assemble(seed, [first, *later], limit)


def _rounds(frontier: list[str], seen: set[str], depth: int,
            fan: int) -> list[list[dict]]:
    """``_NEIGHBOURS`` rows per hop for ``depth`` hops out from ``frontier``."""
    rounds: list[list[dict]] = []
    for _ in range(depth):
        rows = query(_NEIGHBOURS, {"uids": frontier, "fan": fan,
                                   "bulky": BULKY})
        rounds.append(rows)
        frontier = [row["uid"] for row in rows if row["uid"] not in seen]
        seen.update(frontier)
        if not frontier:
            break
    return rounds
