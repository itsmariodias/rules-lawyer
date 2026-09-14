"""Paths, database connection and chat settings, read from ``.env``."""

from __future__ import annotations

from functools import cached_property, lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/dnd_graph_rag/config.py -> the repository root, which holds
# both ``data/`` and the ``.env`` that also configures docker-compose.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# An absolute env_file so the settings resolve the same from any working
# directory, whether the CLI runs in backend/ or uvicorn runs at the root.
_ENV = SettingsConfigDict(env_file=_REPO_ROOT / ".env",
                          env_file_encoding="utf-8", extra="ignore")


class Neo4jSettings(BaseSettings):
    """Connection details for the graph.  ``NEO4J_PASSWORD`` is required."""

    model_config = _ENV | SettingsConfigDict(env_prefix="NEO4J_")

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: SecretStr
    database: str = "neo4j"
    batch_size: int = 1000

    @property
    def auth(self) -> tuple[str, str]:
        return self.user, self.password.get_secret_value()


class ChatSettings(BaseSettings):
    """Agent model, retrieval limits and failure handling."""

    model_config = _ENV | SettingsConfigDict(env_prefix="CHAT_")

    # Keeps the name every Google tool already reads, rather than
    # CHAT_GOOGLE_API_KEY.  Optional only so that the rest of the server —
    # every endpoint that is not a turn — starts without one; the chat itself
    # requires it, and says so rather than answering some other way.
    google_api_key: SecretStr | None = Field(default=None,
                                             validation_alias="GOOGLE_API_KEY")
    # Pinned rather than a "-latest" alias, which would change the agent's
    # behaviour on release without a commit.
    model: str = "gemini-3.8-flash"
    temperature: float = 0.2
    # Candidates *per arm* of the hybrid search, not results: the lexical and
    # the dense index are each asked for this many, and the fusion cuts the
    # union down to ``top_k``.  Wider than the answer on purpose — a passage
    # the other arm ranks highly is worth having in the pool.
    search_limit: int = 8
    # What the model actually reads.  Three, because a fused top of three is
    # about as much of the book as an answer leans on, and everything past it
    # is context the model has to ignore.
    top_k: int = 3
    # Bounds silence, not the answer: reset by every token and every tool
    # result, so it fires only on a stalled call, which neither yields nor
    # raises and so is otherwise indistinguishable from a slow one.
    timeout_seconds: float = 60
    # The agent's own Cypher, bounded two ways.  The row cap is what the
    # model reads; the transaction timeout is what the row cap cannot do,
    # since a cartesian product costs its time server-side before it sends a
    # single row.
    cypher_timeout_seconds: float = 10
    cypher_max_rows: int = 50
    # Run the scripted model in ``chat.stub`` instead of Gemini.  For the
    # suites only — the backend's route tests and e2e, which want a
    # deterministic answer and no quota.  Nothing turns it on in response to
    # a failure: a turn that cannot reach the model fails.
    stub: bool = False

    @field_validator("google_api_key", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """
        ``GOOGLE_API_KEY=`` means no key, not a key that is the empty string.

        A blank line in ``.env`` is how someone turns the key off without
        deleting it.  Without this the empty credential reaches Google and
        comes back seconds later as ``API_KEY_INVALID``, when what the reader
        needs is the sentence that names the file.
        """
        return None if isinstance(value, str) and not value.strip() else value


class EmbeddingSettings(BaseSettings):
    """
    The one-time embedding of the book, and the file that makes it optional.

    Every value here is baked into the header of ``srd_embeddings.idx``, so a
    file generated under different settings is rejected whole rather than
    silently mixing two vector spaces.
    """

    model_config = _ENV | SettingsConfigDict(env_prefix="EMBED_")

    # The same name every Google tool reads, for the same reason ChatSettings
    # gives.  Optional: a complete ``.idx`` is the other way to get vectors,
    # and the one a reader without an API key takes.
    google_api_key: SecretStr | None = Field(default=None,
                                             validation_alias="GOOGLE_API_KEY")
    # Pinned to a GA id rather than a preview or a "-latest" alias: the
    # vectors in the shared file have to stay in the space they were made in.
    model: str = "gemini-embedding-001"
    # Truncated from the model's native 3072 by Matryoshka representation
    # learning, which is why ``embed`` normalises: the API only does that for
    # you at full width.
    dimensions: int = 1536
    task_type: str = "RETRIEVAL_DOCUMENT"
    batch: int = 32
    # About 1500 tokens, inside the model's input cap.  One section in the
    # book exceeds it; the rest are nowhere near.
    max_chars: int = 6000
    # Rows per Neo4j transaction.  Lower than the loader's 1000 because each
    # row carries 1536 floats rather than a paragraph.
    write_batch: int = 200

    @field_validator("google_api_key", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """
        ``GOOGLE_API_KEY=`` means no key, not a key that is the empty string.

        A blank line in ``.env`` is how someone turns the key off without
        deleting it, and it is the only way to reach the offline path from a
        checkout that has one: an unset environment variable does not beat an
        ``.env`` that sets it.  Without this the run reaches Google with an
        empty credential and fails halfway through with a provider error
        instead of the message that names the file.
        """
        return None if isinstance(value, str) and not value.strip() else value


class Settings(BaseSettings):
    """Filesystem paths, plus the three lazily built settings groups."""

    model_config = _ENV | SettingsConfigDict(env_prefix="DND_GRAPH_RAG_")

    # Override when the package is installed outside a checkout.
    root: Path = _REPO_ROOT
    data: Path | None = None
    pdf_name: str = "SRD_CC_v5.2.1.pdf"
    output_name: str = "srd_hierarchy.json"
    # The conversation filenames live here rather than on ChatSettings so the
    # server can report where conversations are stored without an API key.
    checkpoint_name: str = "chat.sqlite"
    # Pins, kept out of the checkpoint file: those tables are LangGraph's to
    # change, and a pin outlives the turns stored beside it.
    store_name: str = "chat-store.sqlite"
    # The embeddings live with the other reproducible output, but the path is
    # overridable on its own: a reader who downloads the file rather than
    # generating it keeps it wherever they like.
    embeddings: Path | None = None
    embeddings_name: str = "srd_embeddings.idx"

    @property
    def data_dir(self) -> Path:
        return self.data.expanduser() if self.data else self.root / "data"

    @property
    def source_dir(self) -> Path:
        return self.data_dir / "source"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def pdf_path(self) -> Path:
        return self.source_dir / self.pdf_name

    @property
    def output_path(self) -> Path:
        return self.output_dir / self.output_name

    @property
    def chat_dir(self) -> Path:
        """Conversation state; kept out of the reproducible ``output/``."""
        return self.data_dir / "chat"

    @property
    def checkpoint_path(self) -> Path:
        return self.chat_dir / self.checkpoint_name

    @property
    def store_path(self) -> Path:
        return self.chat_dir / self.store_name

    @property
    def embeddings_path(self) -> Path:
        """
        Where the vectors are read from and written to.

        On ``Settings`` rather than on ``EmbeddingSettings`` for the reason
        ``checkpoint_name`` is: reading the file needs no API key, so asking
        where it is must not require one either.
        """
        return (self.embeddings.expanduser() if self.embeddings
                else self.output_dir / self.embeddings_name)

    @cached_property
    def chat(self) -> ChatSettings:
        """Built on first access, so neither pipeline needs an API key."""
        return ChatSettings()  # type: ignore[call-arg]

    @cached_property
    def embedding(self) -> EmbeddingSettings:
        """Singular, so it does not collide with the ``embeddings`` path."""
        return EmbeddingSettings()  # type: ignore[call-arg]

    @cached_property
    def neo4j(self) -> Neo4jSettings:
        """Built on first access, so stage 1 never needs a password."""
        return Neo4jSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def markdown_path_for(output: Path) -> Path:
    """The intermediate markdown is written beside the JSON it explains."""
    return output.with_suffix(".md")


def anchors_path_for(markdown: Path) -> Path:
    """The page geometry is written beside the markdown it indexes."""
    return markdown.with_suffix(".anchors.json")
