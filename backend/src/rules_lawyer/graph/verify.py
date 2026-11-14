"""
Post-load checks of the graph against the artifact's own counts.

Expected values come from the document (``meta.counts`` and its
collections), never from the loader's tally.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rules_lawyer.graph import mapping
from rules_lawyer.graph.embeddings import Vectors
from rules_lawyer.graph.model import GraphData
from rules_lawyer.graph.schema import VECTOR_NAME, vector_index_width

if TYPE_CHECKING:  # pragma: no cover
    from neo4j import Session


def _scalar(session: "Session", query: str, **parameters: Any) -> Any:
    return session.run(query, **parameters).single()[0]


def _sections_with_prose(document: dict) -> int:
    """
    Sections with non-blank content, counted from the document.

    Matches the keys ``embeddings.texts`` produces, so a stale ``.idx`` fails
    the embedding check.
    """
    total = 0
    stack = list(document.get("sections") or [])
    while stack:
        node = stack.pop()
        if (node.get("content") or "").strip():
            total += 1
        stack.extend(node.get("subsections") or [])
    return total


def _check(checks: list[dict], name: str, expected: Any, found: Any,
           detail: Any = None) -> None:
    row = {"check": name, "expected": expected, "found": found,
           "ok": expected == found}
    if detail:
        row["detail"] = detail
    checks.append(row)


def verify(document: dict, data: GraphData, session: "Session",
           vectors: Vectors) -> dict:
    """
    Compare the loaded graph with the document and the mapped batches.

    Args:
        document: The stage 1 artifact.
        data: What ``mapping.build`` produced from it.
        session: An open session on the loaded database.
        vectors: The vectors that were written.

    Returns:
        ``ok``, the number of ``checks``, the ``failures``, mapper
        ``warnings``, ``orphans_by_label``, and total node and relationship
        counts.
    """
    checks: list[dict] = []
    counts = document["meta"]["counts"]

    # Exact label sets: `:Section:Rule` would otherwise also count the
    # poisons folded in as `:Section:Rule:Equipment:Poison`.
    for batch in data.nodes:
        labels = "".join(f":{label}" for label in batch.labels)
        found = _scalar(
            session,
            f"MATCH (n{labels}) WHERE size(labels(n)) = {len(batch.labels)} "
            "RETURN count(n)")
        _check(checks, f"nodes {batch.signature}", len(batch), found)

    # Wrappers are in the document but deliberately not in the graph.
    wrappers = mapping.wrapper_groups(document)
    total_sections = _scalar(session, "MATCH (n:Section) RETURN count(n)")
    _check(checks, "sections", counts["sections"] - len(wrappers),
           total_sections)

    for entity_type, expected in counts["entity_types"].items():
        if entity_type == "creature_group":
            expected -= len(wrappers)
        found = _scalar(
            session,
            "MATCH (n:Section {entity_type: $type}) RETURN count(n)",
            type=entity_type)
        _check(checks, f"entity_type {entity_type}", expected, found)
    _check(checks, "creature groups wrapping only their namesake", 0,
           _scalar(session,
                   "MATCH (g:CreatureGroup)-[:HAS_SUBSECTION]->(c:Creature) "
                   "WHERE coalesce(trim(g.content), '') = '' "
                   "AND g.heading = c.heading "
                   "AND COUNT { (g)-[:HAS_SUBSECTION]->() } = 1 "
                   "RETURN count(g)"))
    _check(checks, "creature groups without members", 0,
           _scalar(session, "MATCH (g:CreatureGroup) WHERE g.members IS NULL "
                            "RETURN count(g)"))

    subclasses = sum(len(c.get("subclasses") or [])
                     for c in document["classes"])
    for collection, label, expected in (
            ("glossary", "GlossaryTerm", counts["glossary"]),
            ("equipment", "Equipment", counts["equipment"]),
            ("classes", "Class", counts["classes"]),
            ("subclasses", "Subclass", subclasses),
            ("species", "Species", counts["species"]),
            ("backgrounds", "Background", counts["backgrounds"]),
            ("feats", "Feat", counts["feats"])):
        found = _scalar(session, f"MATCH (n:{label}) RETURN count(n)")
        _check(checks, f"{collection}", expected, found)

    # A record with a heading of its own is that section.
    for label in ("Class", "Subclass", "Species", "Background", "Feat"):
        _check(checks, f"{label} not folded into a section", 0,
               _scalar(session,
                       f"MATCH (n:{label}) WHERE NOT n:Section RETURN count(n)"))
    shared = mapping.shared_glossary_sections(document)
    standalone = sum(1 for term in document["glossary"]
                     if term.get("section_id") in shared)
    _check(checks, "glossary terms sharing a passage", standalone,
           _scalar(session, "MATCH (n:GlossaryTerm) WHERE NOT n:Section "
                            "AND (n)-[:DEFINED_IN]->(:Section) "
                            "RETURN count(n)"))

    printed_levels = sum(len(klass.get("progression", [])) for klass in document["classes"]
                         if klass.get("features_table_id"))
    _check(checks, "class levels defined in their features table", printed_levels,
           _scalar(session, "MATCH (n:ClassLevel)-[:DEFINED_IN]->(:Section:Rule) "
                            "RETURN count(n)"))

    table_rows = sum(1 for item in document["equipment"] if item.get("table_id"))
    _check(checks, "weapon and armour rows defined in their table", table_rows,
           _scalar(session, "MATCH (n:Equipment)-[:DEFINED_IN]->(:Section:Rule) "
                            "RETURN count(n)"))

    _check(checks, "creatures with stat blocks", counts["creatures"],
           _scalar(session,
                   "MATCH (n:Creature) WHERE n.ac IS NOT NULL RETURN count(n)"))

    roots = len(document["sections"])
    _check(checks, "section roots", roots,
           _scalar(session, "MATCH (n:Section) "
                            "WHERE NOT ()-[:HAS_SUBSECTION]->(n) "
                            "RETURN count(n)"))
    _check(checks, "sections with multiple parents", 0,
           _scalar(session, "MATCH (n:Section) "
                            "WHERE size([()-[:HAS_SUBSECTION]->(n) | 1]) > 1 "
                            "RETURN count(n)"))

    reference_types = {r["relation"].upper() for r in document["references"]}
    expected_edges = len(document["references"])
    found_edges = sum(
        _scalar(session, f"MATCH ()-[r:{name}]->() RETURN count(r)")
        for name in sorted(reference_types))
    _check(checks, "reference edges", expected_edges, found_edges)
    _check(checks, "unresolved references", 0, len(data.unresolved),
           detail=data.unresolved[:20])

    abilities = sum(1 for creature in document["creatures"]
                    for field in ("traits", "actions", "bonus_actions",
                                  "reactions", "legendary_actions")
                    for _ in creature.get(field) or [])
    _check(checks, "creature abilities", abilities,
           _scalar(session, "MATCH (n:CreatureAbility) RETURN count(n)"))
    _check(checks, "abilities without a creature", 0,
           _scalar(session, "MATCH (n:CreatureAbility) "
                            "WHERE NOT (:Creature)-[:HAS_ABILITY]->(n) "
                            "RETURN count(n)"))
    with_damage = sum(1 for creature in document["creatures"]
                      for field in ("traits", "actions", "bonus_actions",
                                    "reactions", "legendary_actions")
                      for entry in creature.get(field) or []
                      if entry.get("damage"))
    _check(checks, "abilities carrying damage", with_damage,
           _scalar(session, "MATCH (n:CreatureAbility) "
                            "WHERE n.damage_dice IS NOT NULL RETURN count(n)"))

    _check(checks, "sections with an embedding", _sections_with_prose(document),
           _scalar(session, "MATCH (n:Section) WHERE n.embedding IS NOT NULL "
                            "RETURN count(n)"))
    _check(checks, "embeddings of the wrong width", 0,
           _scalar(session, "MATCH (n:Section) WHERE n.embedding IS NOT NULL "
                            "AND size(n.embedding) <> $width RETURN count(n)",
                   width=vectors.dimensions))
    online = [row for row in session.run("SHOW VECTOR INDEXES").data()
              if row.get("name") == VECTOR_NAME]
    _check(checks, f"{VECTOR_NAME} index online", "ONLINE",
           online[0]["state"] if online else "missing")
    _check(checks, f"{VECTOR_NAME} index width", vectors.dimensions,
           vector_index_width(session))

    # The front matter is an orphan in the book itself, so it is reported,
    # not failed.
    orphans = session.run(
        "MATCH (n) WHERE NOT (n)--() UNWIND labels(n) AS label "
        "RETURN label, count(*) AS total ORDER BY label").data()
    unexpected = _scalar(
        session,
        "MATCH (n) WHERE NOT (n)--() AND NOT n:FrontMatter RETURN count(n)")
    _check(checks, "unexpected orphan nodes", 0, unexpected,
           detail=session.run(
               "MATCH (n) WHERE NOT (n)--() "
               "AND NOT n:FrontMatter RETURN labels(n) AS labels, "
               "coalesce(n.name, n.id, n.key) AS name LIMIT 20").data()
           if unexpected else None)

    failures = [row for row in checks if not row["ok"]]
    return {
        "ok": not failures,
        "checks": len(checks),
        "failures": failures,
        "warnings": data.warnings,
        "orphans_by_label": {row["label"]: row["total"] for row in orphans},
        "nodes": _scalar(session, "MATCH (n) RETURN count(n)"),
        "relationships": _scalar(session, "MATCH ()-[r]->() RETURN count(r)"),
    }
