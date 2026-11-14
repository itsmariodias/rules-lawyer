from __future__ import annotations

import pytest

from rules_lawyer.graph import mapping, schema


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


class TestDropStaleVectorIndex:
    def test_given_an_index_of_another_width_when_checked_then_it_is_dropped(self):
        """Regression: an index of the old width silently indexed nothing."""
        # Given an index created at 768 dimensions
        session = WidthSession(768)

        # When the schema is checked for 1536
        dropped = schema.drop_stale_vector_index(session, 1536)

        # Then the index is dropped so it can be recreated at 1536
        assert dropped
        assert f"DROP INDEX {schema.VECTOR_NAME}" in session.statements

    def test_given_an_index_of_the_same_width_when_checked_then_it_stays(self):
        # Given an index already at 1536 dimensions
        session = WidthSession(1536)

        # When the schema is checked for 1536
        dropped = schema.drop_stale_vector_index(session, 1536)

        # Then nothing is dropped
        assert not dropped
        assert not any(s.startswith("DROP") for s in session.statements)

    def test_given_no_index_when_checked_then_nothing_is_dropped(self):
        # Given a database with no vector index yet
        session = WidthSession(None)

        # When the schema is checked
        # Then there is nothing to drop
        assert not schema.drop_stale_vector_index(session, 1536)


class TestDropStaleConstraints:
    def test_given_a_constraint_on_a_retired_key_when_checked_then_it_is_dropped(self):
        # Given a database still constraining Trait.key beside a current key
        session = ConstraintSession(["trait_key_unique", "section_id_unique"])

        # When stale constraints are dropped
        dropped = schema.drop_stale_constraints(session)

        # Then only the retired one goes
        assert dropped == ["trait_key_unique"]
        assert "DROP CONSTRAINT trait_key_unique IF EXISTS" in session.statements
        assert not any("section_id_unique" in s and s.startswith("DROP")
                       for s in session.statements)

    def test_given_only_current_constraints_when_checked_then_nothing_is_dropped(self):
        # Given exactly the declared constraints
        session = ConstraintSession([schema.constraint_name(label, prop)
                                     for label, prop in schema.NODE_KEYS])

        # When stale constraints are dropped
        # Then there are none
        assert schema.drop_stale_constraints(session) == []


class ConstraintSession:
    """A session whose database holds the given uniqueness constraints."""

    def __init__(self, names: list[str]) -> None:
        self._names = names
        self.statements: list[str] = []

    def run(self, query: str, **parameters):
        self.statements.append(query)
        rows = [{"name": name} for name in self._names]
        return type("Result", (), {"data": lambda _: rows})()


class WidthSession:
    """A session whose vector index, if any, has the given width."""

    def __init__(self, width: int | None) -> None:
        self._width = width
        self.statements: list[str] = []

    def run(self, query: str, **parameters):
        self.statements.append(query)
        row = None if self._width is None else {"dimensions": self._width}
        return type("Result", (), {"single": lambda _: row})()


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
