from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dnd_graph_rag.api import app
from dnd_graph_rag.graph import routes
from dnd_graph_rag.graph.embeddings import MissingEmbeddings


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestGraphHealth:
    def test_given_a_reachable_graph_when_asked_then_the_counts_come_back(
            self, client, monkeypatch):
        # Given a database that answers
        monkeypatch.setattr(routes.pipeline, "counts",
                            lambda: {"uri": "bolt://localhost:7687",
                                     "database": "neo4j",
                                     "nodes": {"Section": 2368},
                                     "relationships": {"HAS_SUBSECTION": 2352}})

        # When health is asked
        response = client.get("/graph/health")

        # Then the status and the contents are reported together
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["nodes"]["Section"] == 2368

    def test_given_an_unreachable_graph_when_asked_then_it_is_unavailable(
            self, client, monkeypatch):
        # Given a database that cannot be reached
        def refuse():
            raise ConnectionError("connection refused")

        monkeypatch.setattr(routes.pipeline, "counts", refuse)

        # When health is asked
        response = client.get("/graph/health")

        # Then it is a service-unavailable carrying the reason
        assert response.status_code == 503
        assert "connection refused" in response.json()["detail"]

    def test_given_a_live_graph_when_asked_then_it_answers_for_itself(self, client,
                                                                      graph):
        # Given a database that is actually up, with the graph loaded
        # When health is asked
        body = client.get("/graph/health").json()

        # Then the counts are queried rather than remembered from a load
        assert body["status"] == "ok"
        assert body["nodes"]["Section"] > 0


class TestGraphLoad:
    def test_given_a_load_when_requested_then_the_verification_report_comes_back(
            self, client, monkeypatch):
        # Given a pipeline that reports a completed load
        monkeypatch.setattr(routes.pipeline, "build_graph",
                            lambda input_path, **kwargs: {
                                "nodes_written": 4260,
                                "validation": {"ok": True, "checks": 64}})

        # When a load is requested
        body = client.post("/graph/load").json()

        # Then the report is the response
        assert body["validation"]["ok"] is True
        assert body["nodes_written"] == 4260

    def test_given_no_body_when_requested_then_it_resets_and_verifies(
            self, client, monkeypatch):
        # Given a pipeline that records how it was called
        seen: dict = {}

        def build_graph(input_path, *, reset, skip_verify, embeddings_path,
                        refresh_embeddings):
            seen.update(input=input_path, reset=reset, skip_verify=skip_verify,
                        embeddings=embeddings_path,
                        refresh=refresh_embeddings)
            return {"validation": {}}

        monkeypatch.setattr(routes.pipeline, "build_graph", build_graph)

        # When a load is requested with no body
        client.post("/graph/load")

        # Then the defaults match the CLI's: reset, verify, configured input
        assert seen == {"input": None, "reset": True, "skip_verify": False,
                        "embeddings": None, "refresh": False}

    def test_given_flags_in_the_body_when_requested_then_they_are_passed_through(
            self, client, monkeypatch):
        # Given a pipeline that records how it was called
        seen: dict = {}

        def build_graph(input_path, *, reset, skip_verify, embeddings_path,
                        refresh_embeddings):
            seen.update(reset=reset, skip_verify=skip_verify,
                        refresh=refresh_embeddings)
            return {"validation": {}}

        monkeypatch.setattr(routes.pipeline, "build_graph", build_graph)

        # When a load is requested that merges, skips the checks and re-embeds
        client.post("/graph/load", json={"reset": False, "skip_verify": True,
                                         "refresh_embeddings": True})

        # Then all three reached the pipeline
        assert seen == {"reset": False, "skip_verify": True, "refresh": True}

    def test_given_no_artifact_when_requested_then_it_is_a_not_found(
            self, client, monkeypatch):
        # Given a pipeline that cannot find the artifact
        def missing(input_path, **kwargs):
            raise FileNotFoundError("artifact not found: x (run dnd-graph-rag parse)")

        monkeypatch.setattr(routes.pipeline, "build_graph", missing)

        # When a load is requested
        response = client.post("/graph/load")

        # Then it is a 404 naming what is missing, as stage 1 answers too
        assert response.status_code == 404
        assert "artifact not found" in response.json()["detail"]

    def test_given_no_embeddings_when_requested_then_it_is_a_conflict(
            self, client, monkeypatch):
        # Given a pipeline with neither vectors on disk nor a key
        def missing(input_path, **kwargs):
            raise MissingEmbeddings(
                "2156 of 2156 sections have no embedding and GOOGLE_API_KEY "
                "is not set.\nEither set it and run `uv run dnd-graph-rag embed`, or "
                "download srd_embeddings.idx and point "
                "DND_GRAPH_RAG_EMBEDDINGS at it.")

        monkeypatch.setattr(routes.pipeline, "build_graph", missing)

        # When a load is requested
        response = client.post("/graph/load")

        # Then it is a conflict carrying the remedy rather than a 500
        assert response.status_code == 409
        assert "dnd-graph-rag embed" in response.json()["detail"]
        assert "DND_GRAPH_RAG_EMBEDDINGS" in response.json()["detail"]
