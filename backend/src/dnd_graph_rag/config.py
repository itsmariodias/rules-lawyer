"""Paths, database connection and chat settings, read from ``.env``."""

from __future__ import annotations

from functools import cached_property, lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/dnd_graph_rag/config.py -> repository root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Absolute so the CLI (run from backend/) and uvicorn (run from the root)
# read the same file.
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
        """``(user, password)`` in the form ``GraphDatabase.driver`` takes."""
        return self.user, self.password.get_secret_value()


class ChatSettings(BaseSettings):
    """Agent model, retrieval limits and failure handling."""

    model_config = _ENV | SettingsConfigDict(env_prefix="CHAT_")

    # Optional so the non-chat endpoints start without a key; a turn without
    # one is answered with 503.
    google_api_key: SecretStr | None = Field(default=None,
                                             validation_alias="GOOGLE_API_KEY")
    # Pinned: a "-latest" alias changes behaviour without a commit.
    model: str = "gemini-3.8-flash"
    temperature: float = 0.2
    # Candidates per search arm; the fusion cuts the union to ``top_k``.
    search_limit: int = 8
    top_k: int = 3
    # Seconds of silence (no token, no tool result) before a turn fails.
    timeout_seconds: float = 60
    # Server-side bound on the agent's Cypher; the row cap cannot stop a
    # cartesian product that runs long before returning anything.
    cypher_timeout_seconds: float = 10
    cypher_max_rows: int = 50
    # Swap Gemini for ``chat.stub``.  Test suites only, never a fallback.
    stub: bool = False

    @field_validator("google_api_key", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """Treat ``GOOGLE_API_KEY=`` as no key, not as an empty credential."""
        return None if isinstance(value, str) and not value.strip() else value


class EmbeddingSettings(BaseSettings):
    """
    Settings for ``srd-embed``.

    Model, dimensions and task type are written into the ``.idx`` header; a
    file made under different values is discarded whole on load.
    """

    model_config = _ENV | SettingsConfigDict(env_prefix="EMBED_")

    # Optional: a complete ``.idx`` needs no key.
    google_api_key: SecretStr | None = Field(default=None,
                                             validation_alias="GOOGLE_API_KEY")
    # Pinned to a GA id: the shared file's vectors must stay in one space.
    model: str = "gemini-embedding-001"
    # Truncated from the native 3072.  The API only normalises at full width,
    # so ``embeddings.embed`` normalises itself.
    dimensions: int = 1536
    task_type: str = "RETRIEVAL_DOCUMENT"
    batch: int = 32
    # ~1500 tokens, under the model's input cap.  One SRD section exceeds it.
    max_chars: int = 6000
    # Rows per transaction; lower than the loader's 1000 because each row is
    # 1536 floats.
    write_batch: int = 200

    @field_validator("google_api_key", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """
        Treat ``GOOGLE_API_KEY=`` as no key, not as an empty credential.

        An unset environment variable does not override ``.env``, so a blank
        value is the only way to force the offline path from a checkout that
        has a key.
        """
        return None if isinstance(value, str) and not value.strip() else value


class Settings(BaseSettings):
    """Filesystem paths, plus the three lazily built settings groups."""

    model_config = _ENV | SettingsConfigDict(env_prefix="DND_GRAPH_RAG_")

    root: Path = _REPO_ROOT
    data: Path | None = None
    pdf_name: str = "SRD_CC_v5.2.1.pdf"
    output_name: str = "srd_hierarchy.json"
    # Not on ChatSettings: building that requires an API key, and every
    # endpoint needs these paths.
    checkpoint_name: str = "chat.sqlite"
    # Pins and titles.  Separate from the checkpointer, whose schema belongs
    # to LangGraph.
    store_name: str = "chat-store.sqlite"
    # Overridable on its own, for a downloaded copy kept outside data/.
    embeddings: Path | None = None
    embeddings_name: str = "srd_embeddings.idx"

    @property
    def data_dir(self) -> Path:
        """``DND_GRAPH_RAG_DATA`` if set, else ``<root>/data``."""
        return self.data.expanduser() if self.data else self.root / "data"

    @property
    def source_dir(self) -> Path:
        """Checked-in inputs (the PDF)."""
        return self.data_dir / "source"

    @property
    def output_dir(self) -> Path:
        """Reproducible stage 1 and embedding outputs."""
        return self.data_dir / "output"

    @property
    def pdf_path(self) -> Path:
        """The SRD PDF."""
        return self.source_dir / self.pdf_name

    @property
    def output_path(self) -> Path:
        """The stage 1 JSON artifact."""
        return self.output_dir / self.output_name

    @property
    def chat_dir(self) -> Path:
        """Conversation state, which unlike ``output/`` is not reproducible."""
        return self.data_dir / "chat"

    @property
    def checkpoint_path(self) -> Path:
        """LangGraph checkpoint database."""
        return self.chat_dir / self.checkpoint_name

    @property
    def store_path(self) -> Path:
        """Pin and title store database."""
        return self.chat_dir / self.store_name

    @property
    def embeddings_path(self) -> Path:
        """
        Where the vectors are read from and written to.

        On ``Settings`` because building ``EmbeddingSettings`` requires an API
        key and reading the file does not.
        """
        return (self.embeddings.expanduser() if self.embeddings
                else self.output_dir / self.embeddings_name)

    @cached_property
    def chat(self) -> ChatSettings:
        """Lazy, so the pipelines run without ``GOOGLE_API_KEY``."""
        return ChatSettings()  # type: ignore[call-arg]

    @cached_property
    def embedding(self) -> EmbeddingSettings:
        """Lazy; singular so it does not collide with ``embeddings``."""
        return EmbeddingSettings()  # type: ignore[call-arg]

    @cached_property
    def neo4j(self) -> Neo4jSettings:
        """Lazy, so ``srd-parse`` runs without ``NEO4J_PASSWORD``."""
        return Neo4jSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read once."""
    return Settings()


def markdown_path_for(output: Path) -> Path:
    """
    The markdown written beside a JSON artifact.

    Args:
        output: Path of ``srd_hierarchy.json`` or equivalent.

    Returns:
        The same path with a ``.md`` suffix.
    """
    return output.with_suffix(".md")


def anchors_path_for(markdown: Path) -> Path:
    """
    The page-geometry file written beside a markdown artifact.

    Args:
        markdown: Path of the markdown the anchors index.

    Returns:
        The same path with an ``.anchors.json`` suffix.
    """
    return markdown.with_suffix(".anchors.json")
