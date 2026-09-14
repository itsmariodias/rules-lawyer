"""
The embeddings: what gets embedded, the file it lives in, and the policy that
decides between generating them and reading them.

None of this needs a network or a database.  ``resolve`` takes its embedder as
an argument for exactly that reason, so the one branch that would call Google
is driven by a fake here.
"""

from __future__ import annotations

import json

import pytest

from dnd_graph_rag.config import EmbeddingSettings
from dnd_graph_rag.graph import embeddings


def settings(**overrides) -> EmbeddingSettings:
    """Settings that never accidentally inherit a real key from ``.env``."""
    values = {"google_api_key": None, "model": "test-model", "dimensions": 3,
              "task_type": "RETRIEVAL_DOCUMENT", "batch": 2, "max_chars": 6000}
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
    """One text per section that has prose, keyed by section id."""

    def test_given_a_tree_when_walked_then_the_ancestors_lead_the_text(self):
        """
        The book has dozens of sections called "Actions"; the tree is the
        only thing that tells them apart, so a bare heading embeds to noise.
        """
        # Given a section nested two deep
        # When the texts are built
        built = embeddings.texts(DOCUMENT)

        # Then its text opens with the path that identifies it
        assert built["1.1.1"].startswith("Monsters > Goblin > Actions\n\n")
        assert "Scimitar" in built["1.1.1"]

    def test_given_a_section_with_no_prose_when_walked_then_it_is_absent(self):
        """A heading with only children has nothing to embed."""
        # Given a tree in which one section is a container only
        # When the texts are built
        built = embeddings.texts(DOCUMENT)

        # Then it is not among them, but its children still are
        assert "1.1" not in built
        assert set(built) == {"1", "1.1.1"}

    def test_given_a_long_section_when_walked_then_it_is_cut_at_a_word(self):
        """
        The cap bounds what is actually sent, and it is applied before the
        digest so that the digest describes what was sent.
        """
        # Given a section whose prose exceeds the cap
        document = {"sections": [{"id": "1", "heading": "Long",
                                  "content": "word " * 400, "subsections": []}]}

        # When the texts are built with a small cap
        built = embeddings.texts(document, max_chars=50)

        # Then the text is inside it and ends on a whole word
        assert len(built["1"]) <= 50
        assert not built["1"].endswith("wor")


class TestDigest:
    """A hash of the embedded text, which is what makes the file a cache."""

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
    """The file: magic, a JSON header, then raw little-endian float32."""

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
        """``keys``, ``digests`` and ``rows`` are parallel by position."""
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
        """By name, rather than by reading somebody else's bytes as floats."""
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
        """A file from a future build is named, not read as floats."""
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


class TestNormalise:
    """Unit length, which the API guarantees only at the native 3072."""

    def test_given_a_vector_when_normalised_then_its_length_is_one(self):
        # Given an unnormalised vector
        # When it is normalised
        unit = embeddings.normalise([3.0, 4.0])

        # Then it points the same way at unit length, as the cosine index
        # and every dot product downstream assume
        assert unit == [0.6, 0.8]

    def test_given_a_zero_vector_when_normalised_then_it_is_left_alone(self):
        """Dividing by its length would be a division by zero."""
        # Given a vector of no length
        # When it is normalised
        # Then it comes back unchanged rather than raising
        assert embeddings.normalise([0.0, 0.0]) == [0.0, 0.0]


class TestResolve:
    """Generating what is missing, reading what is not, or failing loudly."""

    def test_given_a_complete_file_when_resolved_then_nothing_is_embedded(
            self, tmp_path):
        """The path most readers take: a downloaded file and no API key."""
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
        """
        The digests are what make the file a cache: a re-parse that changed
        twelve sections re-embeds twelve sections, not 2156.
        """
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
        """
        So the reader's own file is always complete, and is itself the
        artifact worth sharing.
        """
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
        Whole, not row by row: two vector spaces mixed in one index would
        rank nonsense without ever failing.
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
        """
        Embeddings are required, not an enrichment.  This message is the one
        thing between a reader and a working graph, so it names both ways
        out. It is raised before any session is opened, which is what leaves
        a previously loaded graph standing.
        """
        # Given neither vectors on disk nor a key to make them with
        # When the vectors are resolved
        # Then it refuses, naming the shortfall and both remedies
        with pytest.raises(embeddings.MissingEmbeddings) as raised:
            embeddings.resolve(DOCUMENT, path=tmp_path / "absent.idx",
                               settings=settings(), embedder=refuse)

        message = str(raised.value)
        assert "2 of 2 sections" in message
        assert "srd-embed" in message
        assert "DND_GRAPH_RAG_EMBEDDINGS" in message

    def test_given_a_partial_file_and_no_key_when_resolved_then_it_refuses(
            self, tmp_path):
        """A partial set is never returned: a hole would pass verification."""
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
        """So a file can be held against the parse it was made from."""
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
    """The JSON between the magic and the payload."""
    raw = path.read_bytes()
    start = len(embeddings.MAGIC) + 4
    length = int.from_bytes(raw[len(embeddings.MAGIC):start], "little")
    return raw[start:start + length]


def rewrite_header(path, header: bytes) -> None:
    """Put a different header in front of the same payload."""
    raw = path.read_bytes()
    payload = raw[len(embeddings.MAGIC) + 4 + len(read_header(path)):]
    path.write_bytes(embeddings.MAGIC + len(header).to_bytes(4, "little")
                     + header + payload)


def recorder(calls: list, width: int = 3):
    """An embedder that records what it was asked for and invents vectors."""
    def embed(batch, config, report=lambda _: None):
        calls.append(list(batch))
        return [embeddings.normalise([float(index + 1)] * width)
                for index, _ in enumerate(batch)]

    return embed


def refuse(batch, config, report=lambda _: None):  # pragma: no cover
    raise AssertionError("the embedder should not have been called")


def seed(path, document, *, dimensions: int = 3, only: list[str] | None = None):
    """A file as a previous run would have left it."""
    built = embeddings.texts(document)
    keys = [key for key in built if only is None or key in only]
    embeddings.write(path, embeddings.Vectors(
        model="test-model", dimensions=dimensions,
        task_type="RETRIEVAL_DOCUMENT", keys=keys,
        digests=[embeddings.digest(built[key]) for key in keys],
        rows=[embeddings.normalise([1.0] * dimensions) for _ in keys]))
