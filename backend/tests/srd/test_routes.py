"""The client skips the app's lifespan, which would open the stores in the real ``data/chat``."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dnd_graph_rag.api import app
from dnd_graph_rag.config import get_settings
from dnd_graph_rag.srd import routes
from dnd_graph_rag.srd.artifact import Artifact


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestHealth:
    def test_given_the_configured_paths_when_asked_then_they_and_their_presence_are_reported(self, client):
        # Given the running app
        # When health is asked
        body = client.get("/health").json()

        # Then it names the paths it reads and writes, and whether each exists
        settings = get_settings()
        assert (body["status"], body["pdf"], body["output"]) == ("ok", str(settings.pdf_path),
                                                                str(settings.output_path))
        assert body["pdf_present"] is settings.pdf_path.exists()


class TestParse:
    def test_given_no_pdf_at_the_path_when_parsed_then_it_is_a_404(self, client, tmp_path):
        # Given a PDF path that does not exist
        # When a parse is asked for
        response = client.post("/parse", json={"pdf": str(tmp_path / "missing.pdf")})

        # Then it is refused, naming the path
        assert response.status_code == 404
        assert "missing.pdf" in response.json()["detail"]

    def test_given_a_pdf_when_parsed_then_meta_validation_and_paths_come_back(self, client, tmp_path, monkeypatch):
        # Given a PDF, and a build that returns at once
        pdf = tmp_path / "srd.pdf"
        pdf.write_bytes(b"%PDF")
        out = tmp_path / "out.json"
        artifact = Artifact({"meta": {"pages": 364}, "validation": {"problems": []}}, "# SRD\n", [], [])
        monkeypatch.setattr(routes, "build", lambda path, name: artifact)
        monkeypatch.setattr(routes, "write", lambda built, path: (path, Path("out.md"), Path("out.anchors.json")))

        # When it is parsed
        body = client.post("/parse", json={"pdf": str(pdf), "out": str(out)}).json()

        # Then the document stays on disk and its summary comes back
        assert body == {"meta": {"pages": 364}, "validation": {"problems": []},
                        "written": {"json": str(out), "markdown": "out.md", "anchors": "out.anchors.json"}}


class TestPdf:
    def test_given_no_pdf_when_asked_then_it_is_a_404(self, client, settings_env, tmp_path):
        # Given a data directory with no PDF in it
        settings_env(DND_GRAPH_RAG_DATA=str(tmp_path))

        # When the PDF is asked for
        # Then it is not found
        assert client.get("/pdf").status_code == 404
