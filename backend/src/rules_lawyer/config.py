"""Paths, database connection and chat settings, read from ``.env``."""

from __future__ import annotations

from functools import cached_property, lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BeforeValidator, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from rules_lawyer.providers import PROVIDERS, ModelProvider, Provider

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


class Credentials(BaseSettings):
    """Every provider's key and address, shared by the chat and embeddings.

    What differs between providers is in ``providers``; ``model_provider``
    is the configured one.
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

    @property
    def model_provider(self) -> ModelProvider:
        """The configured provider, which builds the models."""
        return PROVIDERS[self.provider]

    def api_key(self) -> SecretStr | None:
        """The configured provider's key.

        Returns:
            The key, or None if it is unset or the provider takes none.
        """
        return self.model_provider.api_key(self)

    def missing_key(self) -> str | None:
        """The variable the configured provider needs and lacks.

        Returns:
            Its name (``"GOOGLE_API_KEY"``), or None if the key is set or the
            provider takes none.
        """
        variable = self.model_provider.key_variable
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

    # Unset is the provider's pinned model; only Google has one.
    model: str | None = None
    # Unset or blank is the provider's (``ModelProvider.temperature``).
    temperature: Annotated[float | None, BeforeValidator(_blank_is_absent)] = None
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
    def _provider_defaults(self) -> ChatSettings:
        """Default ``model`` to the provider's pinned one, if it has one, and
        ``temperature`` to the provider's.

        Without a model, building it fails, naming ``CHAT_MODEL``: raising
        here would fail every endpoint that reads these settings.
        """
        self.model = self.model or self.model_provider.chat_model
        if self.temperature is None:
            self.temperature = self.model_provider.temperature
        return self


class EmbeddingSettings(Credentials):
    """Settings for ``rules-lawyer embed``.

    Provider, model, dimensions and task type are written into the ``.idx``
    header; a file made under different values is discarded whole on load.
    Keys are optional: a complete ``.idx`` needs none.
    """

    model_config = _ENV | SettingsConfigDict(env_prefix="EMBED_")

    # Unset is the provider's pinned model; only Google has one.
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
        """Refuse a provider that cannot embed; default ``model`` to the
        provider's pinned one, and refuse if it has none."""
        provider = self.model_provider
        if not provider.can_embed:
            embedders = ", ".join(name for name, other in PROVIDERS.items()
                                  if other.can_embed)
            raise ValueError(f"{provider.title} has no embeddings API; set "
                             f"EMBED_PROVIDER to one of {embedders}")
        self.model = self.model or provider.embedding_model
        if self.model is None:
            raise ValueError(f"EMBED_PROVIDER={self.provider} needs EMBED_MODEL")
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

        Named by the embedding provider
        (``ModelProvider.embeddings_name``), so switching provider never
        overwrites the shared Gemini vectors, which cost API calls to remake.
        """
        if self.embeddings:
            return self.embeddings.expanduser()
        provider = self.embedding.model_provider
        return self.output_dir / provider.embeddings_name(self.embeddings_name)

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
