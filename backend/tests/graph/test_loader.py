"""
The loader: query construction, batching, and the write itself.

The query builders are pure strings and run anywhere.  Everything below
``TestLoadGraphAgainstNeo4j`` needs a real database and skips without one —
Neo4j Community serves a single database, so those run against the configured
one and reload it from the artifact, which is what ``srd-graph-load`` does.
"""

from __future__ import annotations

import pytest

from dnd_graph_rag.graph import mapping
from dnd_graph_rag.graph.embeddings import Vectors
from dnd_graph_rag.graph.loader import (EMBEDDING_QUERY, edge_query, load_graph,
                                        node_query, session, write_embeddings)
from dnd_graph_rag.graph.model import EdgeBatch, NodeBatch
from dnd_graph_rag.graph.verify import verify


class TestNodeQuery:
    """MERGE on the key, then overwrite the properties."""

    def test_given_a_batch_when_built_then_it_merges_on_the_key_alone(self):
        # Given a batch of sections
        batch = NodeBatch(labels=["Section"], key="id")

        # When the query is built
        query = node_query(batch)

        # Then the MERGE is on the key, which is what makes a reload a no-op
        assert "MERGE (n:Section {id: row.id})" in query

    def test_given_several_labels_when_built_then_the_rest_are_set_alongside(self):
        # Given a batch carrying a folded entity's labels
        batch = NodeBatch(labels=["Section", "Rule", "Equipment"], key="id")

        # When the query is built
        query = node_query(batch)

        # Then it merges on the first and adds the others
        assert "MERGE (n:Section {id: row.id})" in query
        assert "SET n:Section:Rule:Equipment" in query

    def test_given_a_batch_when_built_then_properties_are_added_not_replaced(self):
        """
        ``SET n += row`` so a node written by one batch and enriched by
        another — a creature's section, then its stat block — keeps both.
        """
        # Given any batch
        # When the query is built
        query = node_query(NodeBatch(labels=["Section"], key="id"))

        # Then the properties are merged into what is already there
        assert "SET n += row" in query
        assert "SET n = row" not in query


class TestEdgeQuery:
    """Both endpoints MATCHed, never MERGEd."""

    def test_given_a_batch_when_built_then_neither_endpoint_is_merged(self):
        """
        A MERGE would invent an empty node for a target that failed to
        resolve, and hide exactly the drift stage 2 exists to catch.
        """
        # Given a relationship batch
        batch = EdgeBatch(type="IMPOSES_CONDITION", start_label="CreatureAbility",
                          start_key="key", end_label="GlossaryTerm",
                          end_key="name")

        # When the query is built
        query = edge_query(batch)

        # Then both ends are matched, and only the relationship is merged
        assert "MATCH (a:CreatureAbility {key: row.start})" in query
        assert "MATCH (b:GlossaryTerm {name: row.end})" in query
        assert "MERGE (a)-[r:IMPOSES_CONDITION]->(b)" in query


class TestLoadGraphBatching:
    """How the rows reach the database, without one to reach."""

    def test_given_more_rows_than_a_batch_when_written_then_they_are_chunked(self):
        # Given 5 nodes and a batch size of 2
        batch = NodeBatch(labels=["Section"], key="id")
        for index in range(5):
            batch.add(id=str(index))
        data = mapping.GraphData(nodes=[batch])
        recorder = RecordingSession()

        # When the graph is loaded
        result = load_graph(data, recorder, vectors=NO_VECTORS, reset=False,
                            batch_size=2)

        # Then the rows arrived in three chunks, and all of them arrived
        assert [len(rows) for rows in recorder.written] == [2, 2, 1]
        assert result["nodes_written"] == 5

    def test_given_nodes_and_edges_when_loaded_then_the_nodes_go_first(self):
        """So every endpoint a relationship matches on already exists."""
        # Given a document with both
        nodes = NodeBatch(labels=["Section"], key="id")
        nodes.add(id="1")
        edges = EdgeBatch(type="HAS_SUBSECTION", start_label="Section",
                          start_key="id", end_label="Section", end_key="id")
        edges.add("1", "1")
        recorder = RecordingSession()

        # When the graph is loaded
        load_graph(mapping.GraphData(nodes=[nodes], edges=[edges]), recorder,
                   vectors=NO_VECTORS, reset=False)

        # Then the node write preceded the relationship write
        queries = [query for query, _ in recorder.writes]
        assert "MERGE (n:Section" in queries[0]
        assert "MERGE (a)-[r:HAS_SUBSECTION]->(b)" in queries[1]

    def test_given_a_report_callable_when_loaded_then_progress_is_announced(self):
        # Given a batch and somewhere to report to
        batch = NodeBatch(labels=["Section"], key="id")
        batch.add(id="1")
        lines: list[str] = []

        # When the graph is loaded with a reporter
        load_graph(mapping.GraphData(nodes=[batch]), RecordingSession(),
                   vectors=NO_VECTORS, reset=False, report=lines.append)

        # Then the run narrated itself, which is what the CLI prints
        assert any("schema" in line for line in lines)
        assert any("nodes: 1" in line for line in lines)

    def test_given_a_load_when_it_finishes_then_the_report_carries_the_findings(self):
        # Given mapped data carrying an unresolved reference and a warning
        data = mapping.GraphData(unresolved=[{"name": "Nonexistent"}],
                                 warnings=["something drifted"])

        # When the graph is loaded
        result = load_graph(data, RecordingSession(), vectors=NO_VECTORS,
                            reset=False)

        # Then what the mapper noticed travels with the result
        assert result["unresolved_references"] == [{"name": "Nonexistent"}]
        assert result["warnings"] == ["something drifted"]


class TestWriteEmbeddings:
    """One vector per section, set onto sections that already exist."""

    def test_given_vectors_when_written_then_each_row_carries_its_own(self):
        # Given two sections' vectors
        vectors = Vectors(model="m", dimensions=2, task_type="t",
                          keys=["1", "2"], digests=["a", "b"],
                          rows=[[1.0, 0.0], [0.0, 1.0]])
        recorder = RecordingSession()

        # When they are written
        written = write_embeddings(vectors, recorder, batch_size=10)

        # Then both went in one batch, keyed by section id
        assert written == 2
        assert recorder.written == [[{"id": "1", "embedding": [1.0, 0.0]},
                                     {"id": "2", "embedding": [0.0, 1.0]}]]

    def test_given_more_vectors_than_a_batch_when_written_then_they_are_chunked(self):
        """
        Smaller batches than the node loader's: each row carries 1536 floats
        rather than a paragraph.
        """
        # Given five vectors and a batch size of two
        vectors = Vectors(model="m", dimensions=1, task_type="t",
                          keys=[str(i) for i in range(5)],
                          digests=["d"] * 5, rows=[[float(i)] for i in range(5)])
        recorder = RecordingSession()

        # When they are written
        write_embeddings(vectors, recorder, batch_size=2)

        # Then they arrived in three chunks
        assert [len(rows) for rows in recorder.written] == [2, 2, 1]

    def test_given_the_query_when_read_then_the_section_is_matched_not_merged(self):
        """
        A key with no section is a stale file, not a licence to invent a
        node — the rule ``edge_query`` follows for the same reason.
        """
        # Given the embedding query
        # When it is read
        # Then it matches an existing section and only sets the property
        assert "MATCH (n:Section {id: row.id})" in EMBEDDING_QUERY
        assert "MERGE" not in EMBEDDING_QUERY

    def test_given_a_load_when_it_finishes_then_the_embeddings_go_in_last(self):
        """Once there is a section for each of them to land on."""
        # Given a section and a vector for it
        nodes = NodeBatch(labels=["Section"], key="id")
        nodes.add(id="1")
        vectors = Vectors(model="m", dimensions=1, task_type="t", keys=["1"],
                          digests=["d"], rows=[[1.0]])
        recorder = RecordingSession()

        # When the graph is loaded
        result = load_graph(mapping.GraphData(nodes=[nodes]), recorder,
                            vectors=vectors, reset=False)

        # Then the vector was written after the node, and counted
        assert "SET n.embedding" in recorder.writes[-1][0]
        assert result["embeddings_written"] == 1


class RecordingSession:
    """
    A session that records the row writes and performs none of them.

    ``execute_write`` hands the unit of work a transaction to run on, and the
    recorder is both.  Schema statements arrive through the same ``run`` with
    no rows, so only the row-carrying calls are recorded as writes.
    """

    def __init__(self) -> None:
        self.writes: list[tuple[str, list[dict]]] = []
        self.written: list[list[dict]] = []

    def run(self, query: str, rows: list[dict] | None = None, **parameters):
        if rows is not None:
            self.writes.append((query, rows))
            self.written.append(rows)
        return FakeResult()

    def execute_write(self, unit_of_work):
        return unit_of_work(self)


class FakeResult:
    def consume(self):
        return type("Summary", (), {
            "counters": type("Counters", (), {"nodes_deleted": 0})()
        })()


# The unit tests above are about batching, not about vectors, so they load
# none: ``load_graph`` requires a set, not a non-empty one.
NO_VECTORS = Vectors(model="none", dimensions=1, task_type="none", keys=[],
                     digests=[], rows=[])


@pytest.fixture(scope="module")
def loaded(document, vectors, graph_session):
    """The real artifact, loaded into a real Neo4j."""
    data = mapping.build(document)
    load_graph(data, graph_session, vectors=vectors, reset=True)
    return document, data, vectors, graph_session


class TestLoadGraphAgainstNeo4j:
    """The load itself, against a database.  Skipped when none is running."""

    def test_given_the_artifact_when_loaded_then_every_check_passes(self, loaded):
        # Given the artifact loaded into the graph
        document, data, vectors, session = loaded

        # When the load is verified against the document's own counts
        report = verify(document, data, session, vectors)

        # Then nothing failed
        assert report["failures"] == []
        assert report["ok"]

    def test_given_the_artifact_when_loaded_then_the_graph_holds_what_was_mapped(
            self, loaded):
        # Given the loaded graph
        _, data, _, session = loaded

        # When its nodes and relationships are counted
        nodes = session.run("MATCH (n) RETURN count(n)").single()[0]
        edges = session.run("MATCH ()-[r]->() RETURN count(r)").single()[0]

        # Then they are exactly what the mapper produced
        assert nodes == data.node_count
        assert edges == data.edge_count

    def test_given_a_loaded_graph_when_loaded_again_then_nothing_doubles(
            self, loaded):
        """Everything MERGEs on a stable key, so a re-run is a no-op."""
        # Given a graph already loaded
        _, data, vectors, session = loaded
        before = session.run("MATCH (n) RETURN count(n)").single()[0]

        # When it is loaded again without a reset
        load_graph(data, session, vectors=vectors, reset=False)

        # Then the counts did not move
        after = session.run("MATCH (n) RETURN count(n)").single()[0]
        assert after == before

    def test_given_a_loaded_graph_when_traversed_then_a_question_crosses_types(
            self, loaded):
        """
        The point of the graph: one traversal from a creature's action,
        through the condition it imposes, to the creatures that ignore it.
        """
        # Given the loaded graph
        *_, session = loaded

        # When both halves of the question are asked
        imposers = session.run(
            "MATCH (c:Creature)-[:HAS_ABILITY]->(:CreatureAbility)"
            "-[:IMPOSES_CONDITION]->(:Condition {name: 'Frightened'}) "
            "RETURN count(DISTINCT c)").single()[0]
        immune = session.run(
            "MATCH (c:Creature)-[:IMMUNE_TO_CONDITION]->"
            "(:Condition {name: 'Frightened'}) RETURN count(c)").single()[0]

        # Then both are answerable from the edges alone
        assert imposers > 0
        assert immune > 0

    def test_given_a_loaded_graph_when_read_then_every_node_locates_its_own_text(
            self, loaded):
        """Retrieval depends on this: a citation must resolve to the book."""
        # Given the loaded graph
        *_, session = loaded

        # When the sections missing their offsets are counted
        missing = session.run(
            "MATCH (n:Section) WHERE n.char_start IS NULL OR "
            "n.page_start IS NULL RETURN count(n)").single()[0]

        # Then there are none
        assert missing == 0


class TestSession:
    """A session against the configured database."""

    def test_given_a_session_when_it_closes_then_the_driver_closes_with_it(
            self, graph_session):
        # Given a database that is up
        # When a session is opened and closed
        with session() as open_session:
            value = open_session.run("RETURN 1 AS one").single()["one"]

        # Then it answered while it was open
        assert value == 1
