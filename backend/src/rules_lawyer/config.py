"""Paths, database connection and chat settings, read from ``.env``."""

from __future__ import annotations

from enum import StrEnum
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/src/rules_lawyer/config.py -> repository root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

# Absolute so the CLI (run from backend/) and uvicorn (run from the root)
# read the same file.
_ENV = SettingsConfigDict(env_file=_REPO_ROOT / ".env",
                          env_file_encoding="utf-8", extra="ignore")


def _blank_is_absent(value: object) -> object:
    """Treat ``GOOGLE_API_KEY=`` as no key, not as an empty credential.

    An unset environment variable does not override ``.env``, so a blank
    value is the only way to force the keyless path from a checkout that has
    a key.
    """
    return None if isinstance(value, str) and not value.strip() else value


# An optional API key, blank counting as unset.
ApiKey = Annotated[SecretStr | None, BeforeValidator(_blank_is_absent)]


class Provider(StrEnum):
    """Who serves a model: the chat's, or the embeddings'."""

    GOOGLE = "google"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


# The variable holding each provider's key.  Ollama runs locally and has none.
KEY_VARIABLES = {
    Provider.GOOGLE: "GOOGLE_API_KEY",
    Provider.OPENAI: "OPENAI_API_KEY",
    Provider.ANTHROPIC: "ANTHROPIC_API_KEY",
}


class Credentials(BaseSettings):
    """Every provider's key and address, shared by the chat and embeddings.

    Keys are passed to clients explicitly: pydantic-settings reads ``.env``
    without exporting it, so a client reading its own variable would not see
    one set there.
    """

    provider: Provider = Provider.GOOGLE
    google_api_key: ApiKey = Field(None, validation_alias="GOOGLE_API_KEY")
    openai_api_key: ApiKey = Field(None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: ApiKey = Field(None, validation_alias="ANTHROPIC_API_KEY")
    # An OpenAI-compatible server (LM Studio, vLLM, OpenRouter); unset is
    # OpenAI itself.
    openai_base_url: str | None = Field(None, validation_alias="OPENAI_BASE_URL")
    ollama_base_url: str = Field("http://localhost:11434",
                                 validation_alias="OLLAMA_BASE_URL")

    def api_key(self) -> SecretStr | None:
        """The configured provider's key.

        Returns:
            The key, or None if it is unset or the provider takes none.
        """
        return {
            Provider.GOOGLE: self.google_api_key,
            Provider.OPENAI: self.openai_api_key,
            Provider.ANTHROPIC: self.anthropic_api_key,
        }.get(self.provider)

    def missing_key(self) -> str | None:
        """The variable the configured provider needs and lacks.

        Returns:
            Its name (``"GOOGLE_API_KEY"``), or None if the key is set or the
            provider takes none.
        """
        variable = KEY_VARIABLES.get(self.provider)
        return variable if variable and self.api_key() is None else None


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


class ChatSettings(Credentials):
    """Agent model, retrieval limits and failure handling.

    Keys are optional so the non-chat endpoints start without one; a turn
    without one is answered with 503.
    """

    model_config = _ENV | SettingsConfigDict(env_prefix="CHAT_")

    # Required for every provider but Google, whose default is pinned: a
    # "-latest" alias changes behaviour without a commit.
    model: str | None = None
    # Blank omits it, for models that accept only their own (OpenAI's
    # reasoning models).
    temperature: Annotated[float | None, BeforeValidator(_blank_is_absent)] = 0.2
    # Unset leaves the provider's default.
    max_tokens: int | None = None
    # Candidates per search arm; the fusion cuts the union to ``top_k``.
    search_limit: int = 8
    top_k: int = 3
    # Seconds of silence (no token, no tool result) before a turn fails.
    timeout_seconds: float = 60
    # Server-side bound on the agent's Cypher; the row cap cannot stop a
    # cartesian product that runs long before returning anything.
    cypher_timeout_seconds: float = 10
    cypher_max_rows: int = 50

    @model_validator(mode="after")
    def _pin_gemini(self) -> ChatSettings:
        """Default ``model`` to the pinned Gemini when Google serves it."""
        if self.model is None and self.provider is Provider.GOOGLE:
            self.model = "gemini-3.8-flash"
        return self


class EmbeddingSettings(Credentials):
    """Settings for ``rules-lawyer embed``.

    Provider, model, dimensions and task type are written into the ``.idx``
    header; a file made under different values is discarded whole on load.
    Keys are optional: a complete ``.idx`` needs none.
    """

    model_config = _ENV | SettingsConfigDict(env_prefix="EMBED_")

    # Required for every provider but Google, whose default is pinned.
    model: str | None = None
    # Gemini's is truncated from the native 3072, and the API only normalises
    # at full width, so ``embeddings.embed`` normalises itself.  Other models
    # must return exactly this width.
    dimensions: int = 1536
    # Gemini only.
    task_type: str = "RETRIEVAL_DOCUMENT"
    batch: int = 32
    # ~1500 tokens, under the model's input cap.  One SRD section exceeds it.
    max_chars: int = 6000
    # Rows per transaction; lower than the loader's 1000 because each row is
    # 1536 floats.
    write_batch: int = 200

    @model_validator(mode="after")
    def _check_model(self) -> EmbeddingSettings:
        """Default ``model`` for Google; refuse a provider that cannot embed.

        Pinned to a GA id: the shared file's vectors must stay in one space.
        """
        if self.provider is Provider.ANTHROPIC:
            raise ValueError("Anthropic has no embeddings API; set "
                             "EMBED_PROVIDER to google, openai or ollama")
        if self.model is None:
            if self.provider is not Provider.GOOGLE:
                raise ValueError(f"EMBED_PROVIDER={self.provider} needs "
                                 f"EMBED_MODEL")
            self.model = "gemini-embedding-001"
        return self


class Settings(BaseSettings):
    """Filesystem paths, plus the three lazily built settings groups."""

    model_config = _ENV | SettingsConfigDict(env_prefix="RULES_LAWYER_")

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
        """``RULES_LAWYER_DATA`` if set, else ``<root>/data``."""
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
        """Where the vectors are read from and written to.

        Each provider but Google gets its own file
        (``srd_embeddings.ollama.idx``), so switching provider never
        overwrites the shared Gemini vectors, which cost API calls to remake.
        """
        if self.embeddings:
            return self.embeddings.expanduser()
        name = Path(self.embeddings_name)
        provider = self.embedding.provider
        if provider is not Provider.GOOGLE:
            name = name.with_suffix(f".{provider}{name.suffix}")
        return self.output_dir / name

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
        """Lazy, so ``rules-lawyer parse`` runs without ``NEO4J_PASSWORD``."""
        return Neo4jSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, read once.

    Returns:
        The settings; ``cache_clear`` makes the next call read them again.
    """
    return Settings()


def markdown_path_for(output: Path) -> Path:
    """The markdown written beside a JSON artifact.

    Args:
        output: Path of ``srd_hierarchy.json`` or equivalent.

    Returns:
        The same path with a ``.md`` suffix.
    """
    return output.with_suffix(".md")


def anchors_path_for(markdown: Path) -> Path:
    """The page-geometry file written beside a markdown artifact.

    Args:
        markdown: Path of the markdown the anchors index.

    Returns:
        The same path with an ``.anchors.json`` suffix.
    """
    return markdown.with_suffix(".anchors.json")
