from __future__ import annotations

import pytest

from dnd_graph_rag.graph import mapping
from dnd_graph_rag.graph.loader import load_graph
from dnd_graph_rag.graph.schema import VECTOR_NAME
# Not via the package: ``graph.verify`` there is the function, not the module.
from dnd_graph_rag.graph.verify import _check, verify


class TestCheck:
    def test_given_agreement_when_recorded_then_the_check_passes(self):
        # Given a check whose two sides agree
        checks: list[dict] = []

        # When it is recorded
        _check(checks, "sections", 2368, 2368)

        # Then it is marked ok, carrying both sides for a report to print
        assert checks == [{"check": "sections", "expected": 2368,
                           "found": 2368, "ok": True}]

    def test_given_disagreement_when_recorded_then_the_check_fails(self):
        # Given a check whose sides differ
        checks: list[dict] = []

        # When it is recorded
        _check(checks, "sections", 2368, 2367)

        # Then it is a failure, and says what was expected against what is there
        assert checks[0]["ok"] is False
        assert (checks[0]["expected"], checks[0]["found"]) == (2368, 2367)

    def test_given_a_detail_when_recorded_then_it_rides_along(self):
        # Given a failing check with examples of what went wrong
        checks: list[dict] = []

        # When it is recorded with a detail
        _check(checks, "unresolved references", 0, 2,
                            detail=[{"name": "Nonexistent"}])

        # Then the examples are in the row, so a report can name them
        assert checks[0]["detail"] == [{"name": "Nonexistent"}]

    def test_given_nothing_to_add_when_recorded_then_no_empty_detail_is_kept(self):
        # Given a passing check with no detail
        checks: list[dict] = []

        # When it is recorded
        _check(checks, "sections", 1, 1, detail=[])

        # Then the row stays as small as what it says
        assert "detail" not in checks[0]


@pytest.fixture(scope="module")
def verified(document, vectors, graph_session):
    """Load the artifact and verify it."""
    data = mapping.build(document)
    load_graph(data, graph_session, vectors=vectors, reset=True)
    return verify(document, data, graph_session, vectors)


class TestVerify:
    def test_given_a_loaded_graph_when_verified_then_every_check_passes(
            self, verified):
        # Given the artifact loaded into the graph
        # When it is verified
        # Then nothing failed, and there were checks to fail
        assert verified["failures"] == []
        assert verified["ok"] is True
        assert verified["checks"] > 60

    def test_given_a_loaded_graph_when_verified_then_the_totals_are_reported(
            self, verified):
        # Given the verification report
        # When the totals are read
        # Then the graph's size is stated rather than only asserted
        assert verified["nodes"] > 0
        assert verified["relationships"] > 0

    def test_given_a_loaded_graph_when_verified_then_every_section_with_prose_is_embedded(
            self, verified, vectors, graph_session):
        # Given the verified graph
        embedded = graph_session.run(
            "MATCH (n:Section) WHERE n.embedding IS NOT NULL "
            "RETURN count(n)").single()[0]

        # When that is held against the vectors that were loaded
        # Then every one of them landed, and the check agrees
        assert embedded == len(vectors)
        assert not [c for c in verified["failures"]
                    if "embedding" in c["check"]]

    def test_given_a_loaded_graph_when_verified_then_the_vector_index_is_online(
            self, verified, graph_session):
        # Given the verified graph
        indexes = {row["name"]: row["state"]
                   for row in graph_session.run("SHOW VECTOR INDEXES").data()}

        # When the vector index is looked up
        # Then it is there and serving
        assert indexes.get(VECTOR_NAME) == "ONLINE"

    def test_given_a_loaded_graph_when_verified_then_the_two_orphan_groups_are_exempt(
            self, verified):
        """
        Front matter and the 20 table-only weapon and armour rows are orphans
        in the book itself.
        """
        # Given the verification report
        orphans = verified["orphans_by_label"]

        # When the orphans are read
        # Then they exist, and they are the two groups the book itself creates
        assert set(orphans) <= {"Section", "FrontMatter", "Equipment",
                                "Weapon", "Armor"}
        assert not [c for c in verified["failures"]
                    if c["check"] == "unexpected orphan nodes"]
