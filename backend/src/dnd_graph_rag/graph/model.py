"""
The typed contract between the mapper and the loader.

``mapping`` produces :class:`NodeBatch` and :class:`EdgeBatch` objects and
knows nothing about Neo4j; ``loader`` consumes them and knows nothing about
the SRD.  Keeping the seam here is what lets the whole JSON → graph
translation be tested without a database.

A batch is one label (or one relationship type) plus the rows for it.  Rows
are already flattened to values Neo4j accepts — primitives and homogeneous
arrays — because the artifact is full of nested dicts and Neo4j is not.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

# Neo4j stores primitives and homogeneous arrays, nothing else.
_PRIMITIVES = (str, int, float, bool)
Property = str | int | float | bool | list[str] | list[int] | list[float] | None


class NodeBatch(BaseModel):
    """Rows that MERGE on ``key`` and carry ``labels``."""

    labels: list[str]
    key: str
    rows: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def primary(self) -> str:
        """The label rows MERGE on; the rest are set alongside it."""
        return self.labels[0]

    @property
    def signature(self) -> str:
        return ":".join(self.labels)

    def add(self, **row: Any) -> None:
        self.rows.append(clean(row))

    def __len__(self) -> int:
        return len(self.rows)


class EdgeBatch(BaseModel):
    """
    Rows that MATCH both endpoints and MERGE a relationship between them.

    Endpoints are matched, never merged: an edge whose target is missing is a
    finding to report, not a licence to invent an empty node.
    """

    type: str
    start_label: str
    start_key: str
    end_label: str
    end_key: str
    rows: list[dict[str, Any]] = Field(default_factory=list)

    def add(self, start: str, end: str, **properties: Any) -> None:
        self.rows.append({"start": start, "end": end,
                          "properties": clean(properties)})

    def __len__(self) -> int:
        return len(self.rows)


class GraphData(BaseModel):
    """Everything the loader needs, plus what the mapper noticed on the way."""

    nodes: list[NodeBatch] = Field(default_factory=list)
    edges: list[EdgeBatch] = Field(default_factory=list)
    unresolved: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def node_count(self) -> int:
        return sum(len(batch) for batch in self.nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(batch) for batch in self.edges)

    def counts_by_label(self) -> dict[str, int]:
        return {batch.signature: len(batch) for batch in self.nodes}

    def counts_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for batch in self.edges:
            counts[batch.type] = counts.get(batch.type, 0) + len(batch)
        return counts


def clean(row: dict[str, Any]) -> dict[str, Any]:
    """
    Drop keys Neo4j would store as null anyway, keeping properties sparse,
    and reject anything Neo4j could not hold.

    The artifact is full of nested dicts, and a stray one otherwise surfaces
    as a ``CypherTypeError`` partway through a load, naming the value but not
    the field it came from.  Failing here names both.
    """
    kept = {k: v for k, v in row.items() if v is not None and v != []}
    for key, value in kept.items():
        if isinstance(value, list):
            if all(isinstance(item, _PRIMITIVES) for item in value):
                continue
        elif isinstance(value, _PRIMITIVES):
            continue
        raise TypeError(
            f"property {key!r} is not a Neo4j value: {value!r}. Flatten it "
            "into primitives or keep it with as_json().")
    return kept


def as_json(value: Any) -> str | None:
    """
    Keep a nested structure that has no useful flat form.

    Used for the handful of fields — a creature action's ``outcomes``, a
    spell's raw component block — that are worth carrying for retrieval but
    are not worth querying on.
    """
    if value is None or value == {} or value == []:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
