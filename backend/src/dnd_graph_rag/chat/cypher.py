"""
The graph, asked a question directly.

Where ``retrieval`` reads the graph for passages and ``neighbourhood`` reads
it for shape, this lets the agent write the query itself.  It exists for the
question those two answer badly: the *exhaustive* one.  "Which creatures can
make someone Frightened" is twenty rows of Cypher and sixty tool calls of
searching, because a search returns passages and a bounded walk returns a
sample, and neither is a list the model will trust as complete.

**The boundary is the transaction, not a word list.**  The session is opened
``READ_ACCESS`` and the query runs in an explicit transaction, so Neo4j
itself refuses a write with ``Neo.ClientError.Statement.AccessMode`` before
anything happens.  That matters because the obvious alternative — refusing
any query containing ``CREATE`` or ``SET`` — is both weaker and wrong: the
SRD contains a spell called *Create Undead*, so a legitimate
``WHERE s.name = 'Create Undead'`` would be rejected by it.

What read access does *not* cover is guarded separately, and there is
exactly one thing in that class: a procedure.  ``CALL dbms.listConfig()`` is
a read, runs happily in a read transaction, and returns the server's
configuration, so procedures are allow-listed rather than permitted.  ``LOAD
CSV`` is refused too — this server already blocks the URL, but that is its
configuration rather than our decision.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import neo4j

from ..config import get_settings
from .retrieval import driver, query

# --------------------------------------------------------------------------
# The guard


class Refused(ValueError):
    """The query is one we will not run, for a reason worth telling."""


# Strings are cut out before the guard reads anything, so a rule about the
# word CALL is a rule about the Cypher and never about the book: the SRD has
# a *Create Undead*, a *Delete*-free but *Remove Curse*-full glossary, and
# names are exactly what a WHERE clause is full of.
_STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")

# ``CALL {`` and ``CALL (n) {`` are subqueries, not procedures: neither is
# followed by a name, so neither matches.
_PROCEDURE = re.compile(r"\bCALL\s+([A-Za-z_][\w.]*)", re.I)
_LOAD_CSV = re.compile(r"\bLOAD\s+CSV\b", re.I)

# The two the graph is searched through.  Nothing else is needed to answer a
# rules question, and ``dbms.*`` is a read that returns the server's config.
ALLOWED_PROCEDURES = frozenset({
    "db.index.fulltext.querynodes",
    "db.index.vector.querynodes",
})


def guard(cypher: str) -> None:
    """
    Refuse what a read transaction would happily run and we would not.

    Pure, and deliberately short: everything a denylist would traditionally
    carry is already refused by the server one layer down.
    """
    bare = _STRING.sub("''", cypher)
    if _LOAD_CSV.search(bare):
        raise Refused("LOAD CSV is not allowed. Query the graph itself.")
    for name in _PROCEDURE.findall(bare):
        if name.lower() not in ALLOWED_PROCEDURES:
            raise Refused(
                f"CALL {name} is not allowed. The only procedures available "
                f"are {', '.join(sorted(ALLOWED_PROCEDURES))}. Everything "
                "else is a MATCH.")


# --------------------------------------------------------------------------
# The read


def read(cypher: str, *, timeout: float,
         max_rows: int) -> tuple[list[dict], bool]:
    """
    One query, in a transaction that cannot write and cannot run forever.

    Returns the rows and whether there were more.  ``max_rows + 1`` are read
    so that "more than this" is known rather than guessed, and the timeout
    bounds the query the row cap cannot: a cartesian product costs its time
    server-side before a single row is sent.
    """
    settings = get_settings().neo4j
    rows: list[dict] = []
    with driver().session(database=settings.database,
                          default_access_mode=neo4j.READ_ACCESS) as session:
        with session.begin_transaction(timeout=timeout) as transaction:
            result = transaction.run(cypher)
            for record in result:
                rows.append(record.data())
                if len(rows) > max_rows:
                    break
    if len(rows) > max_rows:
        return rows[:max_rows], True
    return rows, False


# --------------------------------------------------------------------------
# The schema

# What the label lists never say, and every one of these cost real debugging
# time to learn.  Derived facts go below, from the graph; these are the ones
# no introspection can state.
ORIENTATION = """\
- Nodes are multi-label: `:Section:Spell` is one node, so `MATCH (n:Spell)`
  and `MATCH (n:Section)` can return the same node. Match on the most
  specific label.
- `:Section` is the SRD's heading tree and carries `id`, the dotted string
  (`10.3.116`) that is the only citable identifier. RETURN it whenever the
  answer will cite the row.
- A creature, a gear item and a poison *are* their section, so a `:Creature`
  has an `id`. A `:CreatureAbility`, `:GlossaryTerm`, `:Weapon` or `:Class`
  is not a section and has none: reach the section through `HAS_ABILITY`,
  `DEFINED_IN` or `CARRIES` when you need something to cite.
- `:CreatureAbility` is keyed `key` (`Goblin|actions/Bite`) and carries
  `name`, `creature`, `category`, `description`, `save_ability`, `save_dc`,
  `attack_bonus`, `damage_dice`, `damage_types`.
- `:GlossaryTerm` is keyed on `name` and carries a second label for its kind
  (`:Condition`, `:DamageType`, `:Action`), so a condition is
  `(:GlossaryTerm:Condition {name: 'Frightened'})`.
- Every `:Section` has `heading`, `content`, `entity_type`, `page_start`.
  A `:Creature` adds `cr`, `ac`, `hp_average`, `creature_type`; a `:Spell`
  adds `level`, `school`, `concentration`, `ritual`.
- An effect usually reaches its target through an intermediate node, so a
  question about creatures is a two- or three-hop pattern rather than one
  edge. A creature imposes a condition through its ability
  (`(:Creature)-[:HAS_ABILITY]->()-[:IMPOSES_CONDITION]->(:Condition)`) and
  also through a spell that ability casts
  (`(:Creature)-[:HAS_ABILITY]->()-[:REFERENCES_SPELL]->(:Spell)-[:IMPOSES_CONDITION]->(:Condition)`).
  A "which creatures" question wants every such path: cover them in one query
  with a UNION or a variable-length pattern, rather than running each on its
  own and guessing at what none of them returned.
- RETURN the columns that answer the whole question, not just the names. An
  ability's `description`, `save_ability` and `save_dc` are what "and how do
  they do it" is asking for, and they come back with the row; fetching each
  one afterwards with get_srd_section is the same answer for twenty times the
  work.\
"""

_SHAPES = """
MATCH (a)-[r]->(b)
RETURN type(r) AS rel, labels(a) AS source, labels(b) AS target,
       count(*) AS total
ORDER BY rel, total DESC
"""


def _form(labels: list[str]) -> str:
    """
    A label set as it would be written in a MATCH.

    ``:Section`` is dropped where anything else is present, for the reason it
    is dropped everywhere else: it is on 2368 nodes and says nothing about
    which one this is.  On a node that is *only* a section it is all there
    is, so it stays.
    """
    specific = [label for label in labels if label != "Section"]
    return ":" + ":".join(specific or ["Section"])


def _sides(counts: dict[str, int], cap: int = 4) -> str:
    ordered = sorted(counts, key=lambda form: (-counts[form], form))
    shown = "|".join(f"({form})" for form in ordered[:cap])
    if len(ordered) > cap:
        shown += f"|…{len(ordered) - cap} more"
    return shown


@lru_cache(maxsize=1)
def shapes() -> str:
    """
    Which labels each relationship actually joins, read off the data.

    Derived rather than written down, because a hand-kept schema in a prompt
    drifts from the loader the first time anyone edits ``mapping.py`` and
    nothing fails — the model simply writes Cypher against a graph that no
    longer exists.  ``db.schema.visualization`` would be the obvious source
    and is not: it reads the token store, which on a multi-label graph
    reports combinations that no node has.  One pass over 11319
    relationships is 0.14s, once per process.
    """
    grouped: dict[str, dict[str, dict[str, int]]] = {}
    for row in query(_SHAPES, {}):
        entry = grouped.setdefault(row["rel"], {"source": {}, "target": {}})
        for side in ("source", "target"):
            form = _form(row[side])
            entry[side][form] = entry[side].get(form, 0) + row["total"]

    return "\n".join(
        f"{_sides(entry['source'])}-[:{rel}]->{_sides(entry['target'])}"
        for rel, entry in sorted(grouped.items()))


def schema() -> str:
    """The whole of what the model is told about the graph."""
    return (f"The SRD graph, for query_srd_graph:\n\n{ORIENTATION}\n\n"
            f"Relationships, as they actually occur in the data:\n\n"
            f"{shapes()}")


# --------------------------------------------------------------------------
# The answer

# A cell is a property, not a passage.  A query that returns whole nodes
# pulls a creature's `content` into every row, so long values are cut here
# and the tool's docstring asks for named properties instead.
#
# Wide enough for the longest thing anyone legitimately selects.  At 200 it
# cut 22% of ability descriptions, and the ones it cut were the interesting
# ones — a trait with a saving throw and a duration is longer than a trait
# without — so the model read the truncated mechanics, went to
# get_srd_section for the rest, and paid a call per row for a column it had
# already been given. 600 cuts 18 of 1314.
CELL_CHARS = 600

# What the cell cap cannot bound: fifty rows of six columns.  Rows are
# dropped whole rather than cells being squeezed, because a half-populated
# row reads as a fact about the book.
TOTAL_CHARS = 12_000


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        text = ", ".join(_cell(item) for item in value)
    elif isinstance(value, dict):
        text = ", ".join(f"{k}={_cell(v)}" for k, v in value.items())
    else:
        text = str(value)
    text = text.replace("\n", " ").strip()
    return text[:CELL_CHARS] + "…" if len(text) > CELL_CHARS else text


def render(rows: list[dict], truncated: bool) -> str:
    """
    Rows as a table the model can read and quote from.

    Pipe-separated with a header, because the columns are the ones the query
    asked for and their names are how the model refers back to them.  A cut
    result says so: an answer built on 50 rows that were silently the first
    50 of 300 is the same failure the walk's ``truncated`` exists to prevent.
    """
    if not rows:
        return ("The query ran and matched nothing. Check the labels and "
                "relationship directions against the schema, or widen it.")
    columns = list(rows[0])
    header = " | ".join(columns)

    lines: list[str] = []
    spent = len(header)
    for row in rows:
        line = " | ".join(_cell(row.get(column)) for column in columns)
        if lines and spent + len(line) > TOTAL_CHARS:
            break
        lines.append(line)
        spent += len(line)

    if len(lines) < len(rows):
        count = (f"{len(rows)} rows matched, showing the first {len(lines)}; "
                 "the rest did not fit. Narrow the query or return fewer "
                 "columns")
    elif truncated:
        count = f"{len(rows)} rows, and there are more"
    else:
        count = f"{len(rows)} rows, all of them"
    return f"{count}:\n{header}\n" + "\n".join(lines)
