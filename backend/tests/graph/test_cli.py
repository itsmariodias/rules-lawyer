from __future__ import annotations

import pytest

from dnd_graph_rag.graph import cli
from dnd_graph_rag.graph.embeddings import MissingEmbeddings


@pytest.fixture
def run(monkeypatch, capsys):
    """Run ``main`` with the given argv and a stubbed ``build_graph``."""
    def go(argv: list[str], result: dict | Exception):
        monkeypatch.setattr("sys.argv", ["srd-graph-load", *argv])
        seen: dict = {}

        def build_graph(input_path, *, reset, skip_verify, embeddings_path,
                        refresh_embeddings, report):
            seen.update(input=input_path, reset=reset, skip_verify=skip_verify,
                        embeddings=embeddings_path,
                        refresh=refresh_embeddings)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(cli, "build_graph", build_graph)
        try:
            cli.main()
            code = 0
        except SystemExit as exit_:
            code = exit_.code
        return code, capsys.readouterr(), seen

    return go


def report(ok: bool = True, failures: list | None = None) -> dict:
    return {"validation": {"ok": ok, "checks": 64, "failures": failures or [],
                           "nodes": 4260, "relationships": 11319}}


class TestMain:
    def test_given_a_passing_load_when_run_then_it_succeeds_quietly(self, run):
        # Given a load whose checks all passed
        code, output, _ = run([], report())

        # When the CLI finishes
        # Then it exits zero, having said what is in the graph
        assert code == 0
        assert "64 checks, 0 failed" in output.out
        assert "4260 nodes" in output.out

    def test_given_a_failing_check_when_run_then_it_exits_non_zero(self, run):
        # Given a load with a failed check
        failure = [{"check": "sections", "expected": 2368, "found": 2367,
                    "ok": False}]
        code, output, _ = run([], report(ok=False, failures=failure))

        # When the CLI finishes
        # Then it exits non-zero and the failures are on stderr
        assert code == 1
        assert "1 failed" in output.out
        assert "sections" in output.err

    def test_given_a_skipped_verification_when_run_then_no_verdict_is_printed(
            self, run):
        # Given a load that skipped its checks
        code, output, _ = run(["--skip-verify"], {"validation": {"skipped": True}})

        # When the CLI finishes
        # Then it says so rather than reporting a success nobody checked
        assert code == 0
        assert "validation skipped" in output.out

    def test_given_a_missing_artifact_when_run_then_it_reports_and_exits(self, run):
        # Given a pipeline that cannot find the artifact
        code, output, _ = run([], FileNotFoundError("artifact not found: x"))

        # When the CLI finishes
        # Then the error is on stderr and the exit code says it failed
        assert code == 1
        assert "artifact not found" in output.err

    def test_given_no_embeddings_when_run_then_it_reports_and_exits(self, run):
        # Given a pipeline with neither vectors on disk nor a key
        code, output, _ = run([], MissingEmbeddings(
            "2156 of 2156 sections have no embedding and GOOGLE_API_KEY is "
            "not set.\nEither set it and run `uv run srd-embed`, or download "
            "srd_embeddings.idx and point DND_GRAPH_RAG_EMBEDDINGS at it."))

        # When the CLI finishes
        # Then it exits non-zero having named both ways out, with no traceback
        assert code == 1
        assert "srd-embed" in output.err
        assert "DND_GRAPH_RAG_EMBEDDINGS" in output.err

    def test_given_no_arguments_when_run_then_it_resets_and_verifies(self, run):
        # Given no flags
        _, _, seen = run([], report())

        # When the pipeline is called
        # Then it resets, verifies, and reads the configured artifact
        assert seen["reset"] is True
        assert seen["skip_verify"] is False
        assert seen["refresh"] is False
        assert seen["input"].name == "srd_hierarchy.json"
        # None, so the pipeline falls back to the configured path rather than
        # the CLI deciding it twice.
        assert seen["embeddings"] is None

    def test_given_no_reset_when_run_then_the_existing_graph_is_kept(self, run):
        # Given the flag that merges instead of emptying
        _, _, seen = run(["--no-reset"], report())

        # When the pipeline is called
        # Then it is told not to reset
        assert seen["reset"] is False

    def test_given_an_input_path_when_run_then_it_is_used(self, run, tmp_path):
        # Given an artifact somewhere other than the configured place
        elsewhere = tmp_path / "other.json"

        # When the CLI is run against it
        _, _, seen = run(["--input", str(elsewhere)], report())

        # Then that is what the pipeline was pointed at
        assert seen["input"] == elsewhere

    def test_given_an_embeddings_path_when_run_then_it_is_used(self, run, tmp_path):
        # Given a downloaded file somewhere of the reader's choosing
        elsewhere = tmp_path / "srd_embeddings.idx"

        # When the CLI is run against it
        _, _, seen = run(["--embeddings", str(elsewhere)], report())

        # Then the pipeline reads vectors from there
        assert seen["embeddings"] == elsewhere

    def test_given_refresh_when_run_then_the_cached_file_is_ignored(self, run):
        # Given the flag that re-embeds everything
        _, _, seen = run(["--refresh-embeddings"], report())

        # When the pipeline is called
        # Then it is told not to trust what is on disk
        assert seen["refresh"] is True
