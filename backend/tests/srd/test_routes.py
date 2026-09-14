"""
Stage 1 over HTTP.

The API is a remote trigger for the same run the CLI makes, not a query
layer, so what is worth asserting is that ``/parse`` returns the report and
the paths rather than the document, and that a missing file is a status code
rather than a traceback.

The client is built without the app's lifespan: these routes hold no state,
and opening the conversation stores would write into the real ``data/chat``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dnd_graph_rag.api import app
from dnd_graph_rag.config import get_settings


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestHealth:
    """Whether the input and the output are where they are expected."""

    def test_given_the_configured_paths_when_asked_then_they_are_reported(
            self, client):
        # Given the running app
        # When health is asked
        body = client.get("/health").json()

        # Then it names the paths it would read and write
        settings = get_settings()
        assert body["status"] == "ok"
        assert body["pdf"] == str(settings.pdf_path)
        assert body["output"] == str(settings.output_path)

    def test_given_the_checked_in_pdf_when_asked_then_it_is_reported_present(
            self, client):
        # Given the PDF, which is checked in and never written to
        # When health is asked
        body = client.get("/health").json()

        # Then presence is answered from the filesystem, not assumed
        assert body["pdf_present"] is get_settings().pdf_path.exists()
        assert body["output_present"] is get_settings().output_path.exists()


class TestParse:
    """The pipeline, triggered remotely."""

    def test_given_a_missing_pdf_when_parsed_then_it_is_a_not_found(self, client,
                                                                     tmp_path):
        # Given a PDF path nothing has been written to
        missing = tmp_path / "nowhere.pdf"

        # When a parse is requested against it
        response = client.post("/parse", json={"pdf": str(missing),
                                               "out": str(tmp_path / "o.json")})

        # Then the failure is reported as one rather than as a traceback
        assert response.status_code == 404
        assert "nowhere.pdf" in response.json()["detail"]

    def test_given_a_run_when_it_finishes_then_the_document_is_not_in_the_body(
            self, client, monkeypatch, tmp_path):
        """
        The artifact on disk is the interface — it is several megabytes, and
        the graph loader reads it from there.
        """
        # Given a pipeline that reports a run without doing one
        from dnd_graph_rag.srd import routes

        monkeypatch.setattr(routes.pipeline, "build",
                            lambda pdf, out: {"meta": {"counts": {}},
                                              "validation": {"ok": True},
                                              "sections": ["…"]})

        # When a parse is requested
        body = client.post("/parse",
                           json={"out": str(tmp_path / "out.json")}).json()

        # Then the report and the paths come back, and the tree does not
        assert set(body) == {"meta", "validation", "written"}
        assert body["written"]["json"].endswith("out.json")
        assert body["written"]["markdown"].endswith("out.md")

    def test_given_no_body_at_all_when_parsed_then_the_configured_paths_are_used(
            self, client, monkeypatch):
        # Given a pipeline that records what it was asked to read and write
        from dnd_graph_rag.srd import routes

        seen = {}

        def build(pdf, out):
            seen["pdf"], seen["out"] = pdf, out
            return {"meta": {}, "validation": {}}

        monkeypatch.setattr(routes.pipeline, "build", build)

        # When a parse is requested with no body
        client.post("/parse")

        # Then the pipeline's own defaults apply, and the output is configured
        assert seen["pdf"] is None
        assert seen["out"] == get_settings().output_path


class TestPdf:
    """The source PDF, for the facsimile the chat shows beside a citation."""

    def test_given_the_pdf_when_fetched_then_it_is_served_as_a_pdf(self, client):
        # Given the checked-in source document
        if not get_settings().pdf_path.exists():
            pytest.skip("no PDF checked out")

        # When it is fetched
        response = client.get("/pdf")

        # Then it arrives as a PDF the browser can render
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"

    def test_given_the_pdf_when_fetched_then_it_is_cacheable(self, client):
        """The one checked-in input never changes, and it is 5.8 MB."""
        # Given the source document
        if not get_settings().pdf_path.exists():
            pytest.skip("no PDF checked out")

        # When it is fetched
        response = client.get("/pdf")

        # Then the browser is told not to refetch it per citation
        assert "max-age" in response.headers["cache-control"]

    def test_given_no_pdf_when_fetched_then_it_is_a_not_found(self, client,
                                                              settings_env,
                                                              tmp_path):
        # Given settings pointing at a data directory with no PDF in it
        settings_env(DND_GRAPH_RAG_DATA=str(tmp_path))

        # When the PDF is fetched
        response = client.get("/pdf")

        # Then it is reported missing rather than served as an empty file
        assert response.status_code == 404
