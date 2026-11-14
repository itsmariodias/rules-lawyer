"""The agent's four tools.

Each tool's docstring is its description to the model, parsed by LangChain,
so it is prompt text.  Results are prose led by ``[section_id]`` so the
model can cite them.  Each also returns an artifact (see ``Result``) that
the UI reads and the model never sees.
"""

from __future__ import annotations

from langchain_core.tools import tool

from rules_lawyer.chat import cypher, neighbourhood, retrieval
from rules_lawyer.config import get_settings

# ``(content, artifact)``.  The artifact rides on the ToolMessage, hidden from
# the model, and drives the UI's trace row.
#
# ``status`` is one of:
#   ok       the call did what was asked
#   empty    it ran and matched nothing, which is an answer, not a fault
#   refused  we would not run it (an unknown filter, a banned procedure)
#   failed   it ran and broke (bad Cypher, a dead connection)
# ``subject`` replaces a dotted-id argument with the heading it names.
Result = tuple[str, dict]


def _result(content: str, status: str, summary: str,
            subject: str | None = None) -> Result:
    """Pair tool content with its trace artifact."""
    artifact = {"status": status, "summary": summary}
    if subject:
        artifact["subject"] = subject
    return content, artifact


# Not every entity_type: "front_matter" and "creature_group" narrow nothing
# useful.
SEARCHABLE_TYPES = [
    "spell", "creature", "magic_item", "rule", "class", "subclass",
    "class_feature", "glossary_term", "equipment", "feat", "origin", "trap",
    "environmental_effect", "contagion",
]


@tool(parse_docstring=True, response_format="content_and_artifact")
def search_srd(query: str, entity_type: str | None = None) -> Result:
    """Search the D&D 5e SRD for rules text matching a query.

    Blends a keyword search with a meaning-based one, so a paraphrase finds
    the right passage even when it shares no words with the book.

    Args:
        query: What to search for, such as "grappled condition" or "what
            happens when a creature is knocked down". A phrase works as well
            as keywords, though the rulebook's own terms are still the
            sharpest query.
        entity_type: Optional filter, one of spell, creature, magic_item,
            rule, class, subclass, class_feature, glossary_term, equipment,
            feat, origin, trap, environmental_effect, contagion. Omit it
            unless the question is clearly about one kind of thing.
    """
    if entity_type and entity_type not in SEARCHABLE_TYPES:
        return _result(f"Unknown entity_type {entity_type!r}. "
                       f"Valid values: {', '.join(SEARCHABLE_TYPES)}.",
                       "refused", f"unknown type {entity_type!r}")

    chat = get_settings().chat
    passages = retrieval.hybrid_search(
        query,
        limit=chat.top_k,
        candidates=chat.search_limit,
        types=[entity_type] if entity_type else None,
    )
    # Only when both arms are empty: the dense arm always has a nearest
    # neighbour, so this needs a blank query or no API key.
    if not passages:
        return _result(
            f"No SRD sections matched {query!r}. Try fewer words, or the "
            "term the rulebook uses.", "empty", "nothing found")
    return _result(
        "\n\n---\n\n".join(passage.for_model() for passage in passages),
        "ok", f"{len(passages)} passage{'s' if len(passages) > 1 else ''}")


@tool(parse_docstring=True, response_format="content_and_artifact")
def get_srd_section(section_id: str) -> Result:
    """Fetch the full text of one SRD section by its id.

    Use this when a search result is truncated, or to read a parent or child
    section that a previous result pointed at.

    Args:
        section_id: A dotted section id such as "11.2.46.1", exactly as it
            appears in square brackets in a search result.
    """
    found = retrieval.get_section(section_id.strip())
    if found is None:
        return _result(
            f"No section with id {section_id!r}. Ids come from search "
            "results and look like 5.3.12 or 11.2.46.1.",
            "empty", "no such section")

    passage, context = found
    parts = [passage.for_model(max_chars=8000)]
    if context["parent"]:
        parts.append(f"Parent: [{context['parent']['id']}] "
                     f"{context['parent']['heading']}")
    if context["children"]:
        listed = ", ".join(f"[{c['id']}] {c['heading']}"
                           for c in context["children"][:25])
        parts.append(f"Subsections: {listed}")
    return _result("\n\n".join(parts), "ok", passage.section_id,
                   subject=passage.heading or "(untitled)")


# The section a derived node was printed in: the stat block owning an
# ability, or the section a glossary term or table row is DEFINED_IN.
_PRINTED_IN = """
MATCH (n) WHERE elementId(n) IN $uids
OPTIONAL MATCH (owner:Section)-[:HAS_ABILITY]->(n)
OPTIONAL MATCH (n)-[:DEFINED_IN]->(defined:Section)
WITH n, coalesce(owner, defined) AS printed
WHERE printed IS NOT NULL
RETURN elementId(n) AS uid, printed.id AS section_id,
       coalesce(printed.heading, printed.name) AS heading
"""


def _printed_in(nodes: list[dict]) -> dict[str, dict]:
    """The citable section each non-section node was printed in.

    Without it the model searched for each such node by name, one call apiece.

    Args:
        nodes: Nodes from ``neighbourhood``.

    Returns:
        Element id to ``{"uid", "section_id", "heading"}``, for the nodes
        that have one.
    """
    uids = [n["uid"] for n in nodes if not n["section_id"]]
    if not uids:
        return {}
    return {row["uid"]: row for row in retrieval.query(_PRINTED_IN,
                                                       {"uids": uids})}


def _describe(node: dict, printed: dict[str, dict] | None = None) -> str:
    """One node as a line, with the id to cite for it.

    A section cites itself; a derived node cites where it was printed, or
    is marked "do not cite" if it was printed nowhere.
    """
    labels = ", ".join(node["labels"]) or "node"
    if node["section_id"]:
        return f"[{node['section_id']}] {node['name']} ({labels})"
    where = (printed or {}).get(node["uid"])
    if where:
        return (f"{node['name']} ({labels}; printed in "
                f"[{where['section_id']}] {where['heading']} — cite that)")
    owner = node.get("owner")
    # The book prints a dozen "Swallow"s; the owner disambiguates.
    whose = f" of {owner}" if owner else ""
    return f"{node['name']} ({labels}{whose}; no section id, do not cite)"


def _anchor_of(edge: dict, nodes: dict[str, dict]) -> tuple[str, bool]:
    """The end of an edge the walk reached first (the shallower; the source on a
    tie), and whether the edge points away from it.
    """
    source, target = nodes[edge["source"]], nodes[edge["target"]]
    if target["depth"] < source["depth"]:
        return edge["target"], False
    return edge["source"], True


def _render(data: dict) -> str:
    """A neighbourhood as indented prose, grouped by anchor, type and direction.

    Groups the fan cap cut read "121 in the graph, 8 shown".
    """
    nodes = {node["uid"]: node for node in data["nodes"]}
    printed = _printed_in(data["nodes"])
    cut = {(t["uid"], t["type"], t["direction"]): t for t in data["truncated"]}

    groups: dict[tuple[str, str, bool], list[dict]] = {}
    for edge in data["edges"]:
        anchor, outgoing = _anchor_of(edge, nodes)
        far = edge["target"] if outgoing else edge["source"]
        groups.setdefault((anchor, edge["type"], outgoing), []).append(nodes[far])

    root = nodes[data["root"]]
    lines = [f"{_describe(root, printed)} — {root['degree']} connections"]
    if root["summary"]:
        lines.append(root["summary"])

    ordered = sorted(nodes.values(), key=lambda n: (n["depth"], n["name"]))
    for node in ordered:
        here = [key for key in groups if key[0] == node["uid"]]
        if not here:
            continue
        if node["uid"] != root["uid"]:
            lines.append(f"\nFrom {_describe(node, printed)}:")
        else:
            lines.append("\nConnected to:")
        for key in sorted(here, key=lambda k: (k[1], not k[2])):
            _, type_, outgoing = key
            way = "outgoing" if outgoing else "incoming"
            shown = groups[key]
            group = cut.get((node["uid"], type_, "out" if outgoing else "in"))
            count = (f"{group['total']} in the graph, {len(shown)} shown"
                     if group else f"{len(shown)}")
            lines.append(f"  {type_}, {way} — {count}:")
            lines.extend(f"    {_describe(far, printed)}"
                         for far in sorted(shown, key=lambda n: n["name"]))
    return "\n".join(lines)


# Upper bound on the model's ``fan``.  The node limit bounds the walk anyway.
MAX_FAN = 50


@tool(parse_docstring=True, response_format="content_and_artifact")
def explore_srd_graph(section_id: str, depth: int = 1,
                      fan: int = neighbourhood.FAN) -> Result:
    """Show what one SRD section is connected to in the rules graph.

    Use this when the question is about relationships rather than wording:
    which creatures impose a condition and through which ability, what deals
    a damage type, what a class feature grants, what a spell references. A
    search returns passages; only this returns the edges between them. Start
    from a section id a search result gave you.

    Args:
        section_id: A dotted section id such as "11.2.114", exactly as it
            appears in square brackets in a search result.
        depth: How many hops out to walk, 1 to 3. One hop is what the section
            is directly joined to; a condition's section is the condition, so
            one hop reaches what imposes it. Damage types and poison types
            share one passage each and are separate term nodes DEFINED_IN it,
            so when a first hop shows only DEFINED_IN, walk it again at depth
            2 to reach what actually points at those terms.
        fan: How many neighbours to show per relationship, up to 50. Raise it
            to see more of a group reported as "22 in the graph, 8 shown".
            It widens every group at once and the walk is still bounded in
            total, so for a list that must be complete use query_srd_graph
            instead; this is for looking around.
    """
    fan = max(1, min(fan, MAX_FAN))
    found = neighbourhood.neighbourhood(
        section_id=section_id.strip(), depth=depth, fan=fan,
        # The node budget is spent in discovery order; without raising it, a
        # wider fan fills the first group and starves the rest.
        limit=max(neighbourhood.LIMIT, fan * 3))
    if found is None:
        return _result(
            f"No section with id {section_id!r}. Ids come from search "
            "results and look like 5.3.12 or 11.2.46.1.",
            "empty", "no such section")
    seed = found["nodes"][0]["name"]
    if not found["edges"]:
        return _result(
            f"{_describe(found['nodes'][0])} is in the graph but has no "
            "relationships. Read it with get_srd_section instead.",
            "empty", "no relationships", subject=seed)
    return _result(_render(found), "ok", f"{len(found['edges'])} edges",
                   subject=seed)


@tool(parse_docstring=True, response_format="content_and_artifact")
def query_srd_graph(cypher_query: str) -> Result:
    """Run a read-only Cypher query against the SRD rules graph.

    This is the tool for an exhaustive question: every creature that imposes
    a condition, every spell on two class lists, every item dealing a damage
    type. A search returns passages and explore_srd_graph returns a sample;
    only this returns all of them, in one call, as rows you can read off.

    The graph's labels and relationships are in your system prompt. Writing
    is refused by the database, so only MATCH and RETURN.

    Args:
        cypher_query: The Cypher to run. RETURN named properties rather than
            whole nodes (`RETURN c.id, c.name, a.name, a.save_dc`, never
            `RETURN c`), since a node drags its whole `content` into every
            row. RETURN the `id` of something citable alongside the answer,
            because an id in square brackets is what a claim is cited with.
            Use LIMIT when you want a few; leave it off when you want all.
    """
    chat = get_settings().chat
    try:
        cypher.guard(cypher_query)
    except cypher.Refused as refusal:
        return _result(str(refusal), "refused", "refused")

    try:
        rows, truncated = cypher.read(cypher_query,
                                      timeout=chat.cypher_timeout_seconds,
                                      max_rows=chat.cypher_max_rows)
    # Returned, not raised: the model fixes the query and retries.
    except Exception as exc:
        return _result(
            f"The query failed: {_reason(exc)}\n\nCheck it against the "
            "schema in your instructions, then try again.",
            "failed", "query failed")
    if not rows:
        return _result(cypher.render(rows, truncated), "empty", "no rows")
    return _result(cypher.render(rows, truncated), "ok",
                   f"{len(rows)} rows{', more' if truncated else ''}")


_ERROR_CHARS = 300


def _reason(exc: Exception) -> str:
    """A Neo4j error as one short sentence for the model."""
    message = str(exc).strip() or exc.__class__.__name__
    # Neo4j's own AccessMode text is "Unexpected error has occurred. See debug
    # log", which gives the model nothing to act on.
    if "AccessMode" in message:
        return ("this is a read-only connection, so no CREATE, MERGE, SET, "
                "DELETE or REMOVE. Only MATCH and RETURN.")
    if len(message) <= _ERROR_CHARS:
        return message
    return message[:_ERROR_CHARS].rsplit(" ", 1)[0] + " …"


TOOLS = [search_srd, get_srd_section, explore_srd_graph, query_srd_graph]
