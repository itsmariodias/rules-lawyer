from __future__ import annotations

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from dnd_graph_rag.api import app


def routes_of(application) -> set[str]:
    """Every path in the app's OpenAPI schema."""
    return set(application.openapi()["paths"])


class TestApp:
    def test_given_the_app_when_built_then_every_stage_is_mounted(self):
        # Given the assembled application
        # When its routes are read
        paths = routes_of(app)

        # Then all three stages are there
        assert {"/health", "/parse", "/pdf"} <= paths          # stage 1
        assert {"/graph/health", "/graph/load"} <= paths       # stage 2
        assert {"/chat", "/chat/threads", "/source/{section_id}",
                "/neighbourhood"} <= paths                     # stage 3

    def test_given_the_app_when_built_then_the_vite_dev_server_may_call_it(self):
        # Given the assembled application
        # When its middleware is read
        origins = [origin
                   for middleware in app.user_middleware
                   for origin in middleware.kwargs.get("allow_origins", [])]

        # Then the dev server's origin is allowed
        assert "http://localhost:5173" in origins

    def test_given_an_unknown_path_when_requested_then_it_is_a_not_found(self):
        # Given the running app
        with TestClient(app) as client:
            # When a path nothing serves is requested
            response = client.get("/nothing-here")

        # Then it is a plain 404
        assert response.status_code == 404

    def test_given_the_app_when_documented_then_the_schema_describes_it(self):
        # Given the assembled application
        client = TestClient(app)

        # When the OpenAPI schema is fetched
        schema = client.get("/openapi.json").json()

        # Then it is the document /docs renders
        assert schema["info"]["title"] == "D&D SRD graph RAG"
        assert "/chat" in schema["paths"]


class TestRouteIsolation:
    @pytest.mark.parametrize("package", ["srd", "graph", "chat"])
    def test_given_a_package_when_imported_then_no_web_framework_comes_with_it(
            self, package):
        # Given a fresh interpreter, so nothing else has imported FastAPI
        script = (f"import dnd_graph_rag.{package}, sys; "
                  "print('fastapi' in sys.modules)")

        # When the package alone is imported
        imported = subprocess.run([sys.executable, "-c", script],
                                  capture_output=True, text=True, check=True)

        # Then the web framework was not pulled in to do it
        assert imported.stdout.strip() == "False"

    def test_given_a_pipeline_imported_alone_when_run_then_no_server_is_needed(self):
        # Given the stage 1 entry points
        from dnd_graph_rag.srd import build, load

        # When they are inspected
        # Then they are callables reachable without the API
        assert callable(build) and callable(load)


class TestLifespan:
    @pytest.fixture
    def isolated(self, settings_env, tmp_path):
        """Settings with the conversation stores in a temporary directory."""
        return settings_env(DND_GRAPH_RAG_DATA=str(tmp_path))

    def test_given_the_app_starts_when_the_lifespan_runs_then_both_stores_are_open(
            self, isolated):
        # Given an app whose conversation files live under a temporary root
        # When the lifespan runs
        with TestClient(app):
            # Then the routes can reach both through app.state
            assert app.state.checkpointer is not None
            assert app.state.store is not None

    def test_given_no_chat_directory_when_the_lifespan_runs_then_it_is_created(
            self, isolated, tmp_path):
        # Given a data directory with no chat/ in it
        assert not (tmp_path / "chat").exists()

        # When the lifespan runs
        with TestClient(app):
            pass

        # Then the directory the stores need was made rather than demanded
        assert (tmp_path / "chat").is_dir()

    def test_given_the_lifespan_ran_when_a_thread_is_listed_then_it_answers_empty(
            self, isolated):
        # Given a fresh set of conversation stores
        with TestClient(app) as client:
            # When the threads are listed
            body = client.get("/chat/threads").json()

        # Then the store answers, with nothing in it
        assert body == {"threads": []}
