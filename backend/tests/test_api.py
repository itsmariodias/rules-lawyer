from __future__ import annotations

import importlib
import logging
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from rules_lawyer import api
from rules_lawyer.api import app
from rules_lawyer.config import get_settings


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


@pytest.fixture
def served(tmp_path, settings_env):
    """The app as the image runs it, over a stand-in frontend build.

    The routes are assembled at import, so the module is reloaded under the
    flag, and again without it afterwards so later tests get the dev app.
    """
    build = tmp_path / "frontend" / "dist"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text("<div id=root></div>")
    (build / "assets" / "app.js").write_text("console.log('app')")
    settings_env(RULES_LAWYER_SERVE_FRONTEND="true",
                 RULES_LAWYER_ROOT=str(tmp_path),
                 RULES_LAWYER_DATA=str(tmp_path / "data"))
    yield importlib.reload(api).app
    get_settings.cache_clear()
    importlib.reload(api)


class TestServeFrontend:
    def test_given_no_flag_when_built_then_the_api_is_at_the_root_and_alone(self):
        # Given the app as the dev server runs it
        with TestClient(app) as client:
            # When the root and the health check are requested
            page = client.get("/", headers={"Accept": "text/html"})
            health = client.get("/health")

        # Then there is no page, and the API answers without a prefix
        assert page.status_code == 404
        assert health.status_code == 200

    def test_given_the_flag_when_the_root_is_opened_then_the_page_is_served(
            self, served):
        # Given the app serving the frontend
        with TestClient(served) as client:
            # When the browser opens the root
            response = client.get("/", headers={"Accept": "text/html"})

        # Then it gets the frontend's page
        assert response.status_code == 200
        assert "<div id=root>" in response.text

    def test_given_the_flag_when_a_thread_path_is_opened_then_the_page_is_served(
            self, served):
        # Given the app serving the frontend
        with TestClient(served) as client:
            # When the browser reloads a conversation's path, which no file has
            response = client.get("/chat/0b6e", headers={"Accept": "text/html"})

        # Then it gets the page, which routes the path itself
        assert response.status_code == 200
        assert "<div id=root>" in response.text

    def test_given_the_flag_when_an_asset_is_requested_then_the_file_is_served(
            self, served):
        # Given the app serving the frontend
        with TestClient(served) as client:
            # When the page asks for one of its scripts
            response = client.get("/assets/app.js")

        # Then it is the file itself
        assert response.text == "console.log('app')"

    def test_given_the_flag_when_the_api_is_called_then_it_answers_under_api(
            self, served):
        # Given the app serving the frontend
        with TestClient(served) as client:
            # When the health check is called where the frontend calls it
            response = client.get("/api/health")

            # Then the API answers, with its stores opened by the lifespan
            assert response.json()["status"] == "ok"
            assert served.state.checkpointer is not None
            assert served.state.store is not None

    def test_given_the_flag_when_an_unknown_api_path_is_called_then_it_is_not_the_page(
            self, served):
        # Given the app serving the frontend
        with TestClient(served) as client:
            # When the frontend calls an API path nothing serves
            response = client.get("/api/nothing-here")

        # Then it is a 404, not the page in its place
        assert response.status_code == 404
        assert "<div id=root>" not in response.text


class TestRouteIsolation:
    @pytest.mark.parametrize("package", ["srd", "graph", "chat"])
    def test_given_a_package_when_imported_then_no_web_framework_comes_with_it(
            self, package):
        # Given a fresh interpreter, so nothing else has imported FastAPI
        script = (f"import rules_lawyer.{package}, sys; "
                  "print('fastapi' in sys.modules)")

        # When the package alone is imported
        imported = subprocess.run([sys.executable, "-c", script],
                                  capture_output=True, text=True, check=True)

        # Then the web framework was not pulled in to do it
        assert imported.stdout.strip() == "False"

    def test_given_the_srd_pipeline_imported_alone_when_inspected_then_no_server_is_needed(self):
        # Given the SRD's build, write and load
        from rules_lawyer.srd.artifact import build, load, write

        # When they are inspected
        # Then they are callables reachable without the API
        assert callable(build) and callable(write) and callable(load)


class TestLifespan:
    @pytest.fixture
    def isolated(self, settings_env, tmp_path):
        """Settings with the conversation stores in a temporary directory."""
        return settings_env(RULES_LAWYER_DATA=str(tmp_path))

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

    @pytest.mark.parametrize("provider", ["google", "openai", "anthropic"])
    def test_given_a_temperature_for_a_hosted_provider_when_started_then_it_warns(
            self, isolated, settings_env, tmp_path, caplog, provider):
        # Given a temperature set for a provider whose models deprecate it
        settings_env(RULES_LAWYER_DATA=str(tmp_path), CHAT_PROVIDER=provider,
                     CHAT_MODEL="test-model", CHAT_TEMPERATURE="0.5")

        # When the app starts
        with caplog.at_level(logging.WARNING, logger="rules_lawyer.api"), \
                TestClient(app):
            pass

        # Then the log says the setting is deprecated, and what to do
        assert "CHAT_TEMPERATURE=0.5 is set, but temperature is deprecated" in caplog.text
        assert "Unset it." in caplog.text

    @pytest.mark.parametrize("environment", [
        {"CHAT_PROVIDER": "google", "CHAT_TEMPERATURE": ""},
        {"CHAT_PROVIDER": "ollama", "CHAT_MODEL": "qwen3", "CHAT_TEMPERATURE": "0.5"},
    ], ids=["google-unset", "ollama-set"])
    def test_given_no_temperature_to_question_when_started_then_nothing_is_logged(
            self, isolated, settings_env, tmp_path, caplog, environment):
        # Given no temperature for a hosted provider, or one for Ollama, which
        # has a default of its own
        settings_env(RULES_LAWYER_DATA=str(tmp_path), **environment)

        # When the app starts
        with caplog.at_level(logging.WARNING, logger="rules_lawyer.api"), \
                TestClient(app):
            pass

        # Then there is nothing to warn about
        assert "CHAT_TEMPERATURE" not in caplog.text

    def test_given_an_invalid_chat_setting_when_started_then_the_app_still_starts(
            self, isolated, settings_env, tmp_path):
        # Given a chat provider that does not exist
        settings_env(RULES_LAWYER_DATA=str(tmp_path), CHAT_PROVIDER="nobody")

        # When the app starts
        with TestClient(app) as client:
            # Then the endpoints that need no model still answer
            assert client.get("/chat/threads").status_code == 200

    def test_given_the_lifespan_ran_when_a_thread_is_listed_then_it_answers_empty(
            self, isolated):
        # Given a fresh set of conversation stores
        with TestClient(app) as client:
            # When the threads are listed
            body = client.get("/chat/threads").json()

        # Then the store answers, with nothing in it
        assert body == {"threads": []}
