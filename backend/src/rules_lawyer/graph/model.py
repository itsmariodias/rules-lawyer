"""
Node and edge batches: what ``mapping`` produces and ``loader`` writes.

Rows hold only values Neo4j accepts (primitives and homogeneous arrays).
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
        """All labels joined with ``:``, e.g. ``Section:Spell``."""
        return ":".join(self.labels)

    def add(self, **row: Any) -> None:
        """
        Append a row of properties.

        Raises:
            TypeError: A property is not a Neo4j value; see ``clean``.
        """
        self.rows.append(clean(row))

    def __len__(self) -> int:
        return len(self.rows)


class EdgeBatch(BaseModel):
    """
    Rows that MATCH both endpoints and MERGE a relationship between them.

    Endpoints are never merged, so a missing target creates no node.
    """

    type: str
    start_label: str
    start_key: str
    end_label: str
    end_key: str
    rows: list[dict[str, Any]] = Field(default_factory=list)

    def add(self, start: str, end: str, **properties: Any) -> None:
        """
        Append an edge.

        Args:
            start: Value of ``start_key`` on the start node.
            end: Value of ``end_key`` on the end node.
            **properties: Relationship properties.

        Raises:
            TypeError: A property is not a Neo4j value; see ``clean``.
        """
        self.rows.append({"start": start, "end": end,
                          "properties": clean(properties)})

    def __len__(self) -> int:
        return len(self.rows)


class GraphData(BaseModel):
    """Every batch, plus unresolved reference targets and mapper warnings."""

    nodes: list[NodeBatch] = Field(default_factory=list)
    edges: list[EdgeBatch] = Field(default_factory=list)
    unresolved: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def node_count(self) -> int:
        """Rows across all node batches."""
        return sum(len(batch) for batch in self.nodes)

    @property
    def edge_count(self) -> int:
        """Rows across all edge batches."""
        return sum(len(batch) for batch in self.edges)

    def counts_by_label(self) -> dict[str, int]:
        """Rows per batch, keyed by ``signature``."""
        return {batch.signature: len(batch) for batch in self.nodes}

    def counts_by_type(self) -> dict[str, int]:
        """Rows per relationship type, summed across batches."""
        counts: dict[str, int] = {}
        for batch in self.edges:
            counts[batch.type] = counts.get(batch.type, 0) + len(batch)
        return counts


def clean(row: dict[str, Any]) -> dict[str, Any]:
    """
    Drop None and empty-list values, and reject what Neo4j cannot store.

    Fails at map time naming the field; Neo4j's ``CypherTypeError`` mid-load
    names only the value.

    Args:
        row: Property name to value.

    Returns:
        The row without None or ``[]`` values.

    Raises:
        TypeError: A value is not a primitive or a list of primitives.
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
    Serialise a nested value that is carried but never queried on.

    Args:
        value: e.g. a creature action's ``outcomes``.

    Returns:
        Sorted-key JSON, or None for None, ``{}`` and ``[]``.
    """
    if value is None or value == {} or value == []:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
