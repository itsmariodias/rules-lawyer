from __future__ import annotations

import pytest

from rules_lawyer.graph import pipeline


class TestBuildGraph:
    def test_given_no_artifact_when_run_then_the_error_says_what_to_do(
            self, tmp_path):
        # Given a path the parser has never written to
        missing = tmp_path / "srd_hierarchy.json"

        # When the graph is built from it
        # Then the failure names both the file and the command that makes it
        with pytest.raises(FileNotFoundError, match="rules-lawyer parse"):
            pipeline.build_graph(missing)

    @pytest.mark.neo4j
    def test_given_a_report_callable_when_run_then_progress_is_announced(
            self, document, vectors, graph_session):
        # Given somewhere to report to
        lines: list[str] = []

        # When the graph is built with a reporter
        pipeline.build_graph(report=lines.append)

        # Then the run narrated each stage, which is what the CLI prints
        assert any("reading" in line for line in lines)
        assert any("mapped" in line for line in lines)
        assert any("verifying" in line for line in lines)

    @pytest.mark.neo4j
    def test_given_verification_is_skipped_when_run_then_it_says_so(
            self, document, vectors, graph_session):
        # Given a load that skips the checks
        result = pipeline.build_graph(skip_verify=True)

        # When the validation is read
        # Then it reports the skip rather than a verdict
        assert result["validation"] == {"ok": None, "skipped": True}

    @pytest.mark.neo4j
    def test_given_a_run_when_it_finishes_then_the_report_names_its_input(
            self, document, vectors, graph_session):
        # Given a load from the configured artifact
        result = pipeline.build_graph(skip_verify=True)

        # When the report is read
        # Then it says which file the graph was built from
        assert result["input"].endswith("srd_hierarchy.json")
        assert result["nodes_written"] > 0
        assert result["relationships_written"] > 0


@pytest.mark.neo4j
class TestCounts:
    def test_given_a_loaded_graph_when_counted_then_it_answers_both_questions(
            self, graph):
        # Given a database that is up, with the graph in it
        # When the counts are taken
        counts = pipeline.counts()

        # Then the connection and the contents are both reported
        assert counts["uri"].startswith("bolt://")
        assert counts["nodes"]["Section"] > 0
        assert counts["relationships"]["HAS_SUBSECTION"] > 0
