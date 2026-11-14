"""Agent-written Cypher: the guard, the read-only transaction, the derived
schema, and the rendered rows.

Writes are refused by Neo4j itself (``READ_ACCESS`` session, explicit
transaction), not by a keyword denylist, which would also reject
``WHERE s.name = 'Create Undead'``.  Read access still permits procedures
such as ``dbms.listConfig()``, so those are allow-listed, and ``LOAD CSV``
is refused.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import neo4j

from rules_lawyer.chat.prompts import prompt
from rules_lawyer.chat.retrieval import driver, query
from rules_lawyer.config import get_settings

# --------------------------------------------------------------------------
# The guard


class Refused(ValueError):
    """A query ``guard`` rejects; the message is shown to the model."""


# String literals are blanked before checking, so names in the book never
# trip the guard.
_STRING = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")

# Subqueries (``CALL {`` and ``CALL (n) {``) have no name, so do not match.
_PROCEDURE = re.compile(r"\bCALL\s+([A-Za-z_][\w.]*)", re.I)
_LOAD_CSV = re.compile(r"\bLOAD\s+CSV\b", re.I)

# Lowercase.  ``dbms.*`` must stay out: it returns server configuration.
ALLOWED_PROCEDURES = frozenset({
    "db.index.fulltext.querynodes",
    "db.index.vector.querynodes",
})


def guard(cypher: str) -> None:
    """Reject ``LOAD CSV`` and any procedure outside ``ALLOWED_PROCEDURES``.

    Writes are not checked here; the read-only transaction refuses them.

    Args:
        cypher: The model's query.

    Raises:
        Refused: The query loads CSV or calls a disallowed procedure.
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
    """Run a query in a read-only transaction with a timeout.

    Args:
        cypher: An already guarded query.
        timeout: Transaction timeout in seconds.
        max_rows: Rows to return; one more is read to detect truncation.

    Returns:
        ``(rows, truncated)``.

    Raises:
        neo4j.exceptions.Neo4jError: Syntax errors, write attempts
            (``Neo.ClientError.Statement.AccessMode``) and timeouts.
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

# Hand-written facts that introspection cannot state; ``shapes`` derives the rest.
ORIENTATION = prompt("graph-orientation")

_SHAPES = """
MATCH (a)-[r]->(b)
RETURN type(r) AS rel, labels(a) AS source, labels(b) AS target,
       count(*) AS total
ORDER BY rel, total DESC
"""


def _form(labels: list[str]) -> str:
    """A label set as written in a MATCH, without ``Section`` unless it is the only one."""
    specific = [label for label in labels if label != "Section"]
    return ":" + ":".join(specific or ["Section"])


def _sides(counts: dict[str, int], cap: int = 4) -> str:
    """The ``cap`` most frequent label forms joined with ``|``, then a remainder count."""
    ordered = sorted(counts, key=lambda form: (-counts[form], form))
    shown = "|".join(f"({form})" for form in ordered[:cap])
    if len(ordered) > cap:
        shown += f"|…{len(ordered) - cap} more"
    return shown


@lru_cache(maxsize=1)
def shapes() -> str:
    """Which label sets each relationship type joins, read from the data.

    Not ``db.schema.visualization``: on a multi-label graph it reports label
    combinations no node has.  About 0.14s; cached for the process.

    Returns:
        One ``(:A)|(:B)-[:REL]->(:C)`` line per relationship type.

    Raises:
        neo4j.exceptions.ServiceUnavailable: The database is unreachable.
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
    """The graph section of the system prompt: orientation plus ``shapes``.

    Returns:
        The section's text.

    Raises:
        neo4j.exceptions.ServiceUnavailable: The database is unreachable.
    """
    return (f"The SRD graph, for query_srd_graph:\n\n{ORIENTATION}\n\n"
            f"Relationships, as they actually occur in the data:\n\n"
            f"{shapes()}")


# --------------------------------------------------------------------------
# The answer

# At 200, 22% of ability descriptions were cut and the model fetched each
# section to read the rest.  600 cuts 18 of 1314.
CELL_CHARS = 600

# Whole rows are dropped past this; a partly emptied row would read as data.
TOTAL_CHARS = 12_000


def _cell(value: Any) -> str:
    """A value as one line of text, cut at ``CELL_CHARS``."""
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
    """Rows as a pipe-separated table for the model.

    Args:
        rows: Query results; columns are taken from the first row.
        truncated: Whether ``read`` stopped at its row cap.

    Returns:
        A count line stating whether the rows are complete, the header and
        the rows; or a hint to check the schema when there are none.
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
