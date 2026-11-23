from __future__ import annotations

import json

import pytest

from rules_lawyer.config import EmbeddingSettings
from rules_lawyer.graph import embeddings


def settings(**overrides) -> EmbeddingSettings:
    """Embedding settings with no API key, whatever ``.env`` says."""
    values = {"google_api_key": None, "model": "test-model", "dimensions": 3,
              "batch": 2, "max_chars": 6000}
    return EmbeddingSettings(**(values | overrides))


DOCUMENT = {
    "meta": {"pdf": "SRD.pdf", "generated": "2026-09-03", "pages": 364},
    "sections": [
        {"id": "1", "heading": "Monsters", "content": "The stat blocks.",
         "subsections": [
             {"id": "1.1", "heading": "Goblin", "content": "",
              "subsections": [
                  {"id": "1.1.1", "heading": "Actions",
                   "content": "Scimitar. Melee Attack.", "subsections": []},
              ]},
         ]},
    ],
}


class TestTexts:
    def test_given_a_tree_when_walked_then_the_ancestors_lead_the_text(self):
        # Given a section nested two deep
        # When the texts are built
        built = embeddings.texts(DOCUMENT)

        # Then its text opens with the path that identifies it
        assert built["1.1.1"].startswith("Monsters > Goblin > Actions\n\n")
        assert "Scimitar" in built["1.1.1"]

    def test_given_a_section_with_no_prose_when_walked_then_it_is_absent(self):
        # Given a tree in which one section is a container only
        # When the texts are built
        built = embeddings.texts(DOCUMENT)

        # Then it is not among them, but its children still are
        assert "1.1" not in built
        assert set(built) == {"1", "1.1.1"}

    def test_given_a_long_section_when_walked_then_it_is_cut_at_a_word(self):
        # Given a section whose prose exceeds the cap
        document = {"sections": [{"id": "1", "heading": "Long",
                                  "content": "word " * 400, "subsections": []}]}

        # When the texts are built with a small cap
        built = embeddings.texts(document, max_chars=50)

        # Then the text is inside it and ends on a whole word
        assert len(built["1"]) <= 50
        assert not built["1"].endswith("wor")


    def test_given_a_document_prefix_when_built_then_it_opens_every_text(self):
        # Given a prefix a model asks for on documents
        # When the texts are built
        built = embeddings.texts(DOCUMENT, document_prefix="doc: ")

        # Then it comes before the heading path
        assert built["1.1.1"] == "doc: Monsters > Goblin > Actions\n\nScimitar. Melee Attack."


class TestDigest:
    def test_given_the_same_text_when_hashed_twice_then_it_agrees(self):
        # Given one text
        # When it is hashed twice
        # Then both agree, so an unchanged section is never re-embedded
        assert embeddings.digest("Prone") == embeddings.digest("Prone")

    def test_given_an_edited_text_when_hashed_then_it_differs(self):
        # Given a text and an edit of it
        # When both are hashed
        # Then they differ, so a re-parse re-embeds what actually changed
        assert embeddings.digest("Prone") != embeddings.digest("Prone.")


class TestWriteAndRead:
    def test_given_vectors_when_round_tripped_then_everything_survives(self, tmp_path):
        # Given two vectors with their keys and digests
        vectors = embeddings.Vectors(
            model="test-model", dimensions=3, task_type="RETRIEVAL_DOCUMENT",
            keys=["1", "11.2.114"], digests=["aaaa", "bbbb"],
            rows=[[1.0, 0.0, 0.0], [0.0, 0.5, 0.5]],
            artifact={"pdf": "SRD.pdf"})

        # When they are written and read back
        embeddings.write(tmp_path / "e.idx", vectors)
        back = embeddings.read(tmp_path / "e.idx")

        # Then nothing moved, to float32 precision
        assert back.keys == vectors.keys
        assert back.digests == vectors.digests
        assert back.rows == vectors.rows
        assert back.model == "test-model"
        assert back.dimensions == 3
        assert back.artifact == {"pdf": "SRD.pdf"}

    def test_given_a_written_file_when_read_then_the_keys_pair_with_the_rows(
            self, tmp_path):
        # Given a file of three vectors
        vectors = embeddings.Vectors(
            model="m", dimensions=2, task_type="t", keys=["a", "b", "c"],
            digests=["1", "2", "3"],
            rows=[[1.0, 1.0], [2.0, 2.0], [3.0, 3.0]])
        embeddings.write(tmp_path / "e.idx", vectors)

        # When it is read and indexed by key
        by_key = embeddings.read(tmp_path / "e.idx").by_key()

        # Then each key kept its own digest and its own row
        assert by_key["b"] == ("2", [2.0, 2.0])

    def test_given_a_file_that_is_not_ours_when_read_then_it_says_so(self, tmp_path):
        # Given a file with the wrong magic
        path = tmp_path / "e.idx"
        path.write_bytes(b"NOTOURS\x00" + b"\x00" * 64)

        # When it is read
        # Then it is refused for what it is
        with pytest.raises(embeddings.BadEmbeddingsFile, match="not an embeddings"):
            embeddings.read(path)

    def test_given_a_truncated_file_when_read_then_it_says_so(self, tmp_path):
        # Given a file whose payload was cut short
        path = tmp_path / "e.idx"
        embeddings.write(path, embeddings.Vectors(
            model="m", dimensions=3, task_type="t", keys=["a", "b"],
            digests=["1", "2"], rows=[[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]]))
        path.write_bytes(path.read_bytes()[:-8])

        # When it is read
        # Then the shortfall is named rather than silently yielding one vector
        with pytest.raises(embeddings.BadEmbeddingsFile, match="truncated"):
            embeddings.read(path)

    def test_given_a_later_format_when_read_then_it_refuses_by_version(self, tmp_path):
        # Given a file whose header claims a format this build does not know
        path = tmp_path / "e.idx"
        embeddings.write(path, embeddings.Vectors(
            model="m", dimensions=1, task_type="t", keys=["a"], digests=["1"],
            rows=[[1.0]]))
        header = json.loads(read_header(path))
        header["version"] = embeddings.VERSION + 1
        rewrite_header(path, json.dumps(header).encode("utf-8"))

        # When it is read
        # Then the version is what it complains about
        with pytest.raises(embeddings.BadEmbeddingsFile, match="format version"):
            embeddings.read(path)

    def test_given_a_file_without_a_provider_when_read_then_it_is_googles(
            self, tmp_path):
        """Files written before providers were configurable hold Gemini
        vectors."""
        # Given a file whose header names no provider
        path = tmp_path / "e.idx"
        embeddings.write(path, embeddings.Vectors(
            model="test-model", dimensions=1, task_type="RETRIEVAL_DOCUMENT",
            keys=["a"], digests=["1"], rows=[[1.0]]))
        header = json.loads(read_header(path))
        del header["provider"]
        rewrite_header(path, json.dumps(header).encode("utf-8"))

        # When it is read
        back = embeddings.read(path)

        # Then it is Google's, and still matches the default settings
        assert back.provider == "google"
        assert back.matches(settings(dimensions=1))


class TestNormalise:
    def test_given_a_vector_when_normalised_then_its_length_is_one(self):
        # Given an unnormalised vector
        # When it is normalised
        unit = embeddings.normalise([3.0, 4.0])

        # Then it points the same way at unit length, as the cosine index
        # and every dot product downstream assume
        assert unit == [0.6, 0.8]

    def test_given_a_zero_vector_when_normalised_then_it_is_left_alone(self):
        # Given a vector of no length
        # When it is normalised
        # Then it comes back unchanged rather than raising
        assert embeddings.normalise([0.0, 0.0]) == [0.0, 0.0]


class TestEmbed:
    def test_given_a_lasting_rate_limit_when_embedded_then_it_gives_up_without_a_last_wait(
            self, monkeypatch):
        # Given an API that answers every call with a rate limit
        from google import genai

        class Limited:
            def __init__(self, **_):
                self.models = self

            def embed_content(self, **_):
                raise RuntimeError("429 RESOURCE_EXHAUSTED")

        waits: list[float] = []
        monkeypatch.setattr(genai, "Client", Limited)
        monkeypatch.setattr(embeddings.time, "sleep", waits.append)

        # When a batch is embedded
        with pytest.raises(RuntimeError, match="rate limited 5 times"):
            embeddings.embed(["text"], settings(google_api_key="not-a-real-key"))

        # Then it waited between attempts, and not after the last
        assert waits == [1, 2, 4, 8]

    @pytest.mark.parametrize(("query", "task"), [
        (False, "RETRIEVAL_DOCUMENT"), (True, "RETRIEVAL_QUERY")])
    def test_given_google_when_embedded_then_each_side_is_sent_as_its_task(
            self, monkeypatch, query, task):
        # Given Gemini, with its client replaced by one recording each call
        from google import genai

        sent: list = []

        class Recording:
            def __init__(self, **_):
                self.models = self

            def embed_content(self, *, model, contents, config):
                sent.append(config)
                return type("Reply", (), {"embeddings": [
                    type("Item", (), {"values": [1.0, 0.0, 0.0]})()
                    for _ in contents]})()

        monkeypatch.setattr(genai, "Client", Recording)

        # When a text is embedded as a section or as a question
        embeddings.embed(["a"], settings(google_api_key="not-a-real-key"),
                         query=query)

        # Then the task named the side, at the configured width
        assert [config.task_type for config in sent] == [task]
        assert sent[0].output_dimensionality == 3

    def test_given_openai_when_embedded_then_its_client_gets_the_key_and_width(
            self, monkeypatch):
        # Given OpenAI configured, and its client replaced by one recording
        # how it was built
        langchain_openai = pytest.importorskip("langchain_openai")
        built: dict = {}

        class Recording:
            def __init__(self, **options):
                built.update(options)

            def embed_documents(self, chunk):
                return [[3.0, 4.0, 0.0] for _ in chunk]

        monkeypatch.setattr(langchain_openai, "OpenAIEmbeddings", Recording)

        # When three texts are embedded in batches of two
        vectors = embeddings.embed(["a", "b", "c"], settings(
            provider="openai", openai_api_key="not-a-real-key"))

        # Then the key and width were passed, and the vectors normalised
        assert built["api_key"] == "not-a-real-key"
        assert built["dimensions"] == 3
        assert vectors == [[0.6, 0.8, 0.0]] * 3

    def test_given_ollama_when_embedded_then_no_key_is_needed(self, monkeypatch):
        # Given Ollama, which runs locally, with its client replaced
        langchain_ollama = pytest.importorskip("langchain_ollama")
        built: dict = {}

        class Recording:
            def __init__(self, **options):
                built.update(options)

            def embed_documents(self, chunk):
                return [[1.0, 0.0, 0.0] for _ in chunk]

        monkeypatch.setattr(langchain_ollama, "OllamaEmbeddings", Recording)

        # When a text is embedded
        vectors = embeddings.embed(["a"], settings(
            provider="ollama", ollama_base_url="http://ollama.test:11434"))

        # Then it went to the configured server
        assert built == {"model": "test-model",
                         "base_url": "http://ollama.test:11434"}
        assert vectors == [[1.0, 0.0, 0.0]]

    def test_given_a_model_of_another_width_when_embedded_then_the_width_is_named(
            self, monkeypatch):
        """Truncating a model that was not trained for it ranks nonsense."""
        # Given a model returning 768 dimensions where 3 are configured
        langchain_ollama = pytest.importorskip("langchain_ollama")

        class Wide:
            def __init__(self, **_):
                pass

            def embed_documents(self, chunk):
                return [[0.1] * 768 for _ in chunk]

        monkeypatch.setattr(langchain_ollama, "OllamaEmbeddings", Wide)

        # When a text is embedded
        # Then it is refused with the setting that fixes it
        with pytest.raises(embeddings.MissingEmbeddings,
                           match="EMBED_DIMENSIONS=768"):
            embeddings.embed(["a"], settings(provider="ollama"))

    def test_given_an_uninstalled_package_when_embedded_then_the_extra_is_named(
            self, monkeypatch):
        # Given OpenAI configured but its package not importable
        import sys

        monkeypatch.setitem(sys.modules, "langchain_openai", None)

        # When a text is embedded
        # Then the failure says how to install it
        with pytest.raises(embeddings.MissingEmbeddings,
                           match="uv sync --extra openai"):
            embeddings.embed(["a"], settings(provider="openai",
                                             openai_api_key="k"))


class TestResolve:
    def test_given_a_complete_file_when_resolved_then_nothing_is_embedded(
            self, tmp_path):
        # Given a file covering every section, and no key
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT)
        calls: list[list[str]] = []

        # When the vectors are resolved
        vectors = embeddings.resolve(DOCUMENT, path=path, settings=settings(),
                                     embedder=recorder(calls))

        # Then all of them came from the file and Google was never reached
        assert len(vectors) == 2
        assert calls == []

    def test_given_a_changed_section_when_resolved_then_only_it_is_embedded(
            self, tmp_path):
        # Given a file made before one section's prose was edited
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT)
        edited = json.loads(json.dumps(DOCUMENT))
        edited["sections"][0]["content"] = "The stat blocks, revised."
        calls: list[list[str]] = []

        # When the vectors are resolved against the new document
        vectors = embeddings.resolve(edited, path=path,
                                     settings=settings(google_api_key="k"),
                                     embedder=recorder(calls))

        # Then exactly one text was sent, and the set is still complete
        assert [len(batch) for batch in calls] == [1]
        assert "revised" in calls[0][0]
        assert len(vectors) == 2

    def test_given_a_changed_section_when_resolved_then_the_file_is_rewritten(
            self, tmp_path):
        # Given a file one section out of date
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT)
        edited = json.loads(json.dumps(DOCUMENT))
        edited["sections"][0]["content"] = "The stat blocks, revised."

        # When the vectors are resolved
        embeddings.resolve(edited, path=path,
                           settings=settings(google_api_key="k"),
                           embedder=recorder([]))

        # Then a second resolve, keyless, needs nothing further
        again = embeddings.resolve(edited, path=path, settings=settings(),
                                   embedder=refuse)
        assert len(again) == 2

    def test_given_a_file_from_another_model_when_resolved_then_it_is_discarded(
            self, tmp_path):
        """
        Vectors from two models in one index would rank nonsense without
        failing.
        """
        # Given a file made at a different width
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT, dimensions=3)
        calls: list[list[str]] = []

        # When the vectors are resolved at another width
        embeddings.resolve(DOCUMENT, path=path,
                           settings=settings(dimensions=4, google_api_key="k"),
                           embedder=recorder(calls, width=4))

        # Then every section was re-embedded, not only the missing ones
        assert sum(len(batch) for batch in calls) == 2

    def test_given_a_file_from_another_provider_when_resolved_then_it_is_discarded(
            self, tmp_path):
        # Given Gemini vectors of the same model name and width
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT, dimensions=3)
        calls: list[list[str]] = []

        # When the vectors are resolved for Ollama
        embeddings.resolve(DOCUMENT, path=path,
                           settings=settings(provider="ollama"),
                           embedder=recorder(calls))

        # Then none of Gemini's were reused
        assert sum(len(batch) for batch in calls) == 2

    def test_given_a_file_from_another_task_when_resolved_then_it_is_discarded(
            self, tmp_path):
        # Given Gemini vectors embedded for some other task
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT, task_type="SEMANTIC_SIMILARITY")
        calls: list[list[str]] = []

        # When the vectors are resolved for Gemini, which embeds the book as
        # RETRIEVAL_DOCUMENT
        embeddings.resolve(DOCUMENT, path=path,
                           settings=settings(google_api_key="k"),
                           embedder=recorder(calls))

        # Then none were reused
        assert sum(len(batch) for batch in calls) == 2

    def test_given_a_new_document_prefix_when_resolved_then_every_section_is_re_embedded(
            self, tmp_path):
        # Given a complete file made without a prefix
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT)
        calls: list[list[str]] = []

        # When the vectors are resolved with a document prefix
        embeddings.resolve(DOCUMENT, path=path,
                           settings=settings(google_api_key="k",
                                             document_prefix="doc: "),
                           embedder=recorder(calls))

        # Then every section was embedded again, with the prefix first
        sent = [text for batch in calls for text in batch]
        assert len(sent) == 2
        assert all(text.startswith("doc: ") for text in sent)

    def test_given_a_task_recorded_for_a_model_without_tasks_when_resolved_then_it_is_kept(
            self, tmp_path):
        """OpenAI files once recorded Gemini's task, which OpenAI ignores."""
        # Given an OpenAI file whose header records a task
        path = tmp_path / "e.openai.idx"
        seed(path, DOCUMENT, provider="openai", task_type="RETRIEVAL_DOCUMENT")

        # When the vectors are resolved for OpenAI
        vectors = embeddings.resolve(DOCUMENT, path=path,
                                     settings=settings(provider="openai"),
                                     embedder=refuse)

        # Then all were reused
        assert len(vectors) == 2

    def test_given_refresh_when_resolved_then_the_file_is_ignored(self, tmp_path):
        # Given a complete file and a key
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT)
        calls: list[list[str]] = []

        # When the vectors are resolved with refresh
        embeddings.resolve(DOCUMENT, path=path,
                           settings=settings(google_api_key="k"),
                           refresh=True, embedder=recorder(calls))

        # Then everything was embedded again regardless
        assert sum(len(batch) for batch in calls) == 2

    def test_given_no_file_and_no_key_when_resolved_then_it_refuses(self, tmp_path):
        # Given neither vectors on disk nor a key to make them with
        # When the vectors are resolved
        # Then it refuses, naming the shortfall and both remedies
        with pytest.raises(embeddings.MissingEmbeddings) as raised:
            embeddings.resolve(DOCUMENT, path=tmp_path / "absent.idx",
                               settings=settings(), embedder=refuse)

        message = str(raised.value)
        assert "2 of 2 sections" in message
        assert "rules-lawyer embed" in message
        assert "RULES_LAWYER_EMBEDDINGS" in message

    def test_given_a_partial_file_and_no_key_when_resolved_then_it_refuses(
            self, tmp_path):
        # Given a file covering one of the two sections, and no key
        path = tmp_path / "e.idx"
        seed(path, DOCUMENT, only=["1"])

        # When the vectors are resolved
        # Then it refuses rather than loading half the book
        with pytest.raises(embeddings.MissingEmbeddings, match="1 of 2"):
            embeddings.resolve(DOCUMENT, path=path, settings=settings(),
                               embedder=refuse)

    def test_given_a_resolve_when_it_finishes_then_the_artifact_is_recorded(
            self, tmp_path):
        # Given a document with provenance in its meta
        path = tmp_path / "e.idx"

        # When the vectors are generated
        embeddings.resolve(DOCUMENT, path=path,
                           settings=settings(google_api_key="k"),
                           embedder=recorder([]))

        # Then the file says which PDF and which parse they came from
        assert embeddings.read(path).artifact == {
            "pdf": "SRD.pdf", "generated": "2026-09-03", "pages": 364}


def read_header(path) -> bytes:
    """The JSON header of an ``.idx`` file."""
    raw = path.read_bytes()
    start = len(embeddings.MAGIC) + 4
    length = int.from_bytes(raw[len(embeddings.MAGIC):start], "little")
    return raw[start:start + length]


def rewrite_header(path, header: bytes) -> None:
    """Replace an ``.idx`` file's header, keeping its payload."""
    raw = path.read_bytes()
    payload = raw[len(embeddings.MAGIC) + 4 + len(read_header(path)):]
    path.write_bytes(embeddings.MAGIC + len(header).to_bytes(4, "little")
                     + header + payload)


def recorder(calls: list, width: int = 3):
    """A fake embedder that records its inputs and returns made-up vectors."""
    def embed(batch, config, report=lambda _: None):
        calls.append(list(batch))
        return [embeddings.normalise([float(index + 1)] * width)
                for index, _ in enumerate(batch)]

    return embed


def refuse(batch, config, report=lambda _: None):  # pragma: no cover
    raise AssertionError("the embedder should not have been called")


def seed(path, document, *, dimensions: int = 3, only: list[str] | None = None,
         provider: str = "google", model: str = "test-model",
         task_type: str = "RETRIEVAL_DOCUMENT"):
    """Write an ``.idx`` file for ``document``."""
    built = embeddings.texts(document)
    keys = [key for key in built if only is None or key in only]
    embeddings.write(path, embeddings.Vectors(
        model=model, dimensions=dimensions, provider=provider,
        task_type=task_type, keys=keys,
        digests=[embeddings.digest(built[key]) for key in keys],
        rows=[embeddings.normalise([1.0] * dimensions) for _ in keys]))
