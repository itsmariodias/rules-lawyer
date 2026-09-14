"""
The four tools the agent may call.

Two read the book — a hybrid search, and one section by id.  Two read the
*graph*, which is the question prose cannot answer and the whole reason
stage 2 exists: ``explore_srd_graph`` for what one section is joined to, and
``query_srd_graph`` for the exhaustive question a bounded walk can only
sample.

Results are prose rather than JSON: the model reads them, and every result
leads with its section id so the model can cite it.  The UI gets the
structured form by another route — ``service`` reads the tool calls off the
message stream — so nothing here serialises for two audiences at once.
"""

from __future__ import annotations

from langchain_core.tools import tool

from ..config import get_settings
from . import cypher, neighbourhood, retrieval

# Entity types a question tends to be *about*, offered to the model as a
# filter.  Deliberately not the full list from the artifact: the long tail
# ("front_matter", "creature_group") narrows nothing a reader would ask for.
# What the trace shows beside each row.  The tools return prose because the
# model reads them, but the UI needs to know how a call went without parsing
# that prose, so every tool also returns an *artifact*: a status and one
# short line.  LangChain puts it on the ToolMessage and never shows it to the
# model, which is the same "structured half by another route" split the tool
# results already use.
#
# ``status`` is one of:
#   ok       the call did what was asked
#   empty    it ran and matched nothing, which is an answer, not a fault
#   refused  we would not run it (an unknown filter, a banned procedure)
#   failed   it ran and broke (bad Cypher, a dead connection)
# ``subject`` is what the row should say it looked *at*, for the calls whose
# own argument is a dotted id.  Nobody knows what `11.2.70` is, and the only
# thing that does is the graph we just read it from.
Result = tuple[str, dict]


def _result(content: str, status: str, summary: str,
            subject: str | None = None) -> Result:
    artifact = {"status": status, "summary": summary}
    if subject:
        artifact["subject"] = subject
    return content, artifact


SEARCHABLE_TYPES = [
    "spell", "creature", "magic_item", "rule", "class_feature",
    "glossary_term", "equipment", "feat", "origin", "trap",
    "environmental_effect", "contagion",
]


@tool(parse_docstring=True, response_format="content_and_artifact")
def search_srd(query: str, entity_type: str | None = None) -> str:
    """Search the D&D 5e SRD for rules text matching a query.

    Blends a keyword search with a meaning-based one, so a paraphrase finds
    the right passage even when it shares no words with the book.

    Args:
        query: What to search for, such as "grappled condition" or "what
            happens when a creature is knocked down". A phrase works as well
            as keywords, though the rulebook's own terms are still the
            sharpest query.
        entity_type: Optional filter, one of spell, creature, magic_item,
            rule, class_feature, glossary_term, equipment, feat, origin,
            trap, environmental_effect, contagion. Omit it unless the
            question is clearly about one kind of thing.
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
    # Only reachable when both arms come back empty — a query of nothing, or
    # a lexical miss in a checkout with no key.  With the dense arm live there
    # is always a nearest neighbour, so "nothing matched" is not something
    # this search can say; judging whether the best guesses answer the
    # question is the model's job, and the prompt says so.
    if not passages:
        return _result(
            f"No SRD sections matched {query!r}. Try fewer words, or the "
            "term the rulebook uses.", "empty", "nothing found")
    return _result(
        "\n\n---\n\n".join(passage.for_model() for passage in passages),
        "ok", f"{len(passages)} passage{'s' if len(passages) > 1 else ''}")


@tool(parse_docstring=True, response_format="content_and_artifact")
def get_srd_section(section_id: str) -> str:
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
    # The heading, not the id: a dotted id says nothing to the person reading
    # the trace, and the UI has nowhere else to learn what it names.
    return _result("\n\n".join(parts), "ok", passage.section_id,
                   subject=passage.heading or "(untitled)")




# The section a derived node was printed in, where one edge says so.  An
# ability belongs to the stat block that lists it; a glossary term to the
# passage defining it.  Nothing else derived — a weapon row, a damage type —
# has a section at all.
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
    """
    Where each uncitable node was printed, so the answer has an id to use.

    Without this the walk is a list of things the model may name and may not
    cite, and the prompt requires a citation — so it goes and searches for
    each one by name, a call apiece.  One query here replaces all of them.
    """
    uids = [n["uid"] for n in nodes if not n["section_id"]]
    if not uids:
        return {}
    return {row["uid"]: row for row in retrieval.query(_PRINTED_IN,
                                                       {"uids": uids})}


def _describe(node: dict, printed: dict[str, dict] | None = None) -> str:
    """
    One node on one line, and what to cite for it.

    Only a node that *is* a section has an id the answer can put in brackets.
    An ability is keyed ``Goblin|actions/Bite`` and a damage type on its name,
    so each is named, said to be whose, and pointed at the section it was
    printed in — the system prompt asks for a citation after every claim, and
    left to itself the model invents one.
    """
    labels = ", ".join(node["labels"]) or "node"
    if node["section_id"]:
        return f"[{node['section_id']}] {node['name']} ({labels})"
    # An ability is named for its entry — "Swallow", "Bite" — and the book
    # prints a dozen of each, so without its owner the line says nothing.
    where = (printed or {}).get(node["uid"])
    if where:
        # The owner is not repeated here: the section it was printed in names
        # the same creature, and twice reads as two facts.
        return (f"{node['name']} ({labels}; printed in "
                f"[{where['section_id']}] {where['heading']} — cite that)")
    owner = node.get("owner")
    whose = f" of {owner}" if owner else ""
    return f"{node['name']} ({labels}{whose}; no section id, do not cite)"


def _anchor_of(edge: dict, nodes: dict[str, dict]) -> tuple[str, bool]:
    """
    Which end of an edge the traversal came from, and whether it points away.

    The shallower end, because that is the one the walk reached first; a tie
    is broken towards the source, so the direction reads as the graph stores
    it.
    """
    source, target = nodes[edge["source"]], nodes[edge["target"]]
    if target["depth"] < source["depth"]:
        return edge["target"], False
    return edge["source"], True


def _render(data: dict) -> str:
    """
    A drawable neighbourhood, spelled as prose for the model.

    The counts are the point.  ``truncated`` carries what the fan cap cut, so
    a group reads "121 in the graph, 8 shown" rather than presenting eight
    neighbours as the whole answer — the same honesty the Graph tab's dashed
    halo gives a reader.
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


# What the model may raise ``fan`` to.  The walk is bounded by
# ``neighbourhood.LIMIT`` nodes regardless, so this cannot run away; it only
# decides how the budget is spent — a wide fan on one group, or a little of
# everything.
MAX_FAN = 50


@tool(parse_docstring=True, response_format="content_and_artifact")
def explore_srd_graph(section_id: str, depth: int = 1,
                      fan: int = neighbourhood.FAN) -> str:
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
            is directly joined to. A condition or damage type is usually
            defined by a section and referenced through a separate term node
            one hop further out, so when a first hop shows only structure
            (HAS_SUBSECTION, DEFINED_IN), walk it again at depth 2 to reach
            what actually points at it.
        fan: How many neighbours to show per relationship, up to 50. Raise it
            to see more of a group reported as "22 in the graph, 8 shown".
            It widens every group at once and the walk is still bounded in
            total, so for a list that must be complete use query_srd_graph
            instead; this is for looking around.
    """
    fan = max(1, min(fan, MAX_FAN))
    found = neighbourhood.neighbourhood(
        section_id=section_id.strip(), depth=depth, fan=fan,
        # The node budget is spent in discovery order, so a fan raised
        # against the default limit widens the first group and starves the
        # rest — asking for more and getting less of what you asked for.
        # It rises with the fan so that a deliberate ask is honoured.
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
def query_srd_graph(cypher_query: str) -> str:
    """Run a read-only Cypher query against the SRD rules graph.

    This is the tool for an exhaustive question — every creature that imposes
    a condition, every spell on two class lists, every item dealing a damage
    type. A search returns passages and explore_srd_graph returns a sample;
    only this returns all of them, in one call, as rows you can read off.

    The graph's labels and relationships are in your system prompt. Writing
    is refused by the database, so only MATCH and RETURN.

    Args:
        cypher_query: The Cypher to run. RETURN named properties rather than
            whole nodes — `RETURN c.id, c.name, a.name, a.save_dc`, never
            `RETURN c` — since a node drags its whole `content` into every
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
    # The message is the model's to act on: a bad label or a wrong direction
    # is a query it can fix and run again, which is the loop working rather
    # than the turn failing.
    except Exception as exc:
        return _result(
            f"The query failed: {_reason(exc)}\n\nCheck it against the "
            "schema in your instructions, then try again.",
            "failed", "query failed")
    if not rows:
        return _result(cypher.render(rows, truncated), "empty", "no rows")
    return _result(cypher.render(rows, truncated), "ok",
                   f"{len(rows)} rows{', more' if truncated else ''}")


# Neo4j's errors arrive with a GQL status object and a stack of framing
# around the one sentence naming the mistake.
_ERROR_CHARS = 300


def _reason(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    # The one the model can cause on purpose, and the one whose own wording
    # ("Unexpected error has occurred. See debug log") tells it nothing.
    if "AccessMode" in message:
        return ("this is a read-only connection, so no CREATE, MERGE, SET, "
                "DELETE or REMOVE. Only MATCH and RETURN.")
    if len(message) <= _ERROR_CHARS:
        return message
    return message[:_ERROR_CHARS].rsplit(" ", 1)[0] + " …"


TOOLS = [search_srd, get_srd_section, explore_srd_graph, query_srd_graph]
