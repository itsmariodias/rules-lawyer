from __future__ import annotations

import pytest

from dnd_graph_rag.graph import mapping, schema


class TestConstraintStatements:
    def test_given_the_node_keys_when_built_then_each_becomes_a_constraint(self):
        # Given the keys nodes are identified by
        # When the statements are built
        statements = schema.constraint_statements()

        # Then there is one per key, and each is idempotent
        assert len(statements) == len(schema.NODE_KEYS)
        assert all("IF NOT EXISTS" in statement for statement in statements)

    def test_given_a_key_when_built_then_the_constraint_names_both_halves(self):
        # Given the statements
        statements = schema.constraint_statements()

        # When the one for the section id is found
        section = next(s for s in statements if "(n:Section)" in s)

        # Then it requires that property to be unique
        assert "REQUIRE n.id IS UNIQUE" in section

    def test_given_the_mapper_when_compared_then_every_merged_key_is_constrained(self):
        # Given the labels and keys the mapper actually merges on
        built = {(batch.primary, batch.key)
                 for batch in mapping.build(EMPTY_DOCUMENT).nodes}

        # When they are held against the declared node keys
        # Then nothing is merged on a key with no constraint behind it
        assert built <= set(schema.NODE_KEYS)


class TestIndexStatements:
    def test_given_the_declared_indexes_when_built_then_each_becomes_a_statement(self):
        # Given the secondary indexes
        # When the statements are built
        statements = schema.index_statements(1536)

        # Then there is one per index, plus the full-text and vector ones
        assert len(statements) == len(schema.INDEXES) + 2

    def test_given_the_statements_when_read_then_the_full_text_index_is_there(self):
        # Given the statements
        # When the full-text one is found
        fulltext = next(s for s in schema.index_statements(1536)
                        if schema.FULLTEXT_NAME in s)

        # Then it covers the two properties an answer is found in
        assert "n.heading, n.content" in fulltext

    def test_given_a_dimension_when_built_then_the_vector_index_carries_it(self):
        # Given the statements built for 1536-wide vectors
        # When the vector one is found
        vector = next(s for s in schema.index_statements(1536)
                      if schema.VECTOR_NAME in s)

        # Then it indexes the embedding at that width, by cosine
        assert "FOR (n:Section) ON (n.embedding)" in vector
        assert "`vector.dimensions`: 1536" in vector
        assert "'cosine'" in vector
        assert "IF NOT EXISTS" in vector


class TestVectorStatement:
    def test_given_a_different_dimension_when_built_then_the_statement_differs(self):
        # Given two widths
        # When each is built
        narrow = schema.vector_statement(768)
        wide = schema.vector_statement(3072)

        # Then the width is the only thing that moved, and it did move
        assert narrow != wide
        assert "768" in narrow and "3072" in wide


class TestReset:
    def test_given_nothing_left_to_delete_when_reset_then_it_stops(self):
        # Given a session that reports one batch deleted and then none
        session = FakeSession([3, 0])

        # When the graph is reset
        deleted = schema.reset(session, batch_size=10)

        # Then it stopped at the empty batch, having counted what it removed
        assert deleted == 3
        assert len(session.calls) == 2


class FakeSession:
    """A session reporting a fixed sequence of deletion counts."""

    def __init__(self, deletions: list[int]) -> None:
        self._deletions = list(deletions)
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **parameters):
        self.calls.append((query, parameters))
        return FakeResult(self._deletions.pop(0))


class FakeResult:
    def __init__(self, deleted: int) -> None:
        self._deleted = deleted

    def consume(self):
        return type("Summary", (), {
            "counters": type("Counters", (), {"nodes_deleted": self._deleted})()
        })()


EMPTY_DOCUMENT = {
    "meta": {"counts": {}}, "sections": [], "creatures": [], "equipment": [],
    "classes": [], "species": [], "backgrounds": [], "feats": [],
    "glossary": [], "references": [], "validation": {},
}
