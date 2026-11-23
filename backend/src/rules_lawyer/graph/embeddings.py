"""One vector per section, and the ``srd_embeddings.idx`` file that carries them.

The file lets a load run without an API key.  A load with neither a complete
file nor a key raises ``MissingEmbeddings``.  Vectors come from Google, OpenAI
(or a server speaking its API) or Ollama, as ``EMBED_PROVIDER`` says.

File format: ``MAGIC``, a little-endian uint32 header length, a JSON header,
then ``count * dimensions`` little-endian float32.
"""

from __future__ import annotations

import json
import math
import struct
import sys
import time
from array import array
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from pathlib import Path

from rules_lawyer.config import EmbeddingSettings
from rules_lawyer.graph.model import Report
from rules_lawyer.providers import Provider

# Attempts per batch while rate limited, waiting 1, 2, 4 and 8 seconds between.
ATTEMPTS = 5

MAGIC = b"DNDEMB\x00"
VERSION = 1
_HEADER_LENGTH = struct.Struct("<I")
_SWAP = sys.byteorder != "little"


class MissingEmbeddings(RuntimeError):
    """No vectors for some sections, and no way to generate them."""


class BadEmbeddingsFile(ValueError):
    """The file is not one of ours, or is truncated."""


@dataclass(slots=True)
class Vectors:
    """Every section's embedding, and a digest of the text embedded.

    Attributes:
        keys: Section ids.
        digests: ``digest`` of each embedded text.  A section whose text
            changes is re-embedded; the rest are reused.
        rows: The vectors.  All three lists are parallel.
        artifact: ``pdf``, ``generated`` and ``pages`` from the document's
            meta, for provenance.
        provider: Who made them.  Files written before providers were
            configurable hold Gemini vectors and no provider.
        task_type: The model's document task (``EmbeddingTasks.document``);
            None for a model that embeds both sides alike.
    """

    model: str
    dimensions: int
    task_type: str | None
    keys: list[str]
    digests: list[str]
    rows: list[list[float]]
    artifact: dict = field(default_factory=dict)
    provider: str = Provider.GOOGLE

    def __len__(self) -> int:
        return len(self.keys)

    def by_key(self) -> dict[str, tuple[str, list[float]]]:
        """Each section's stored digest and vector.

        Returns:
            Section id to ``(digest, vector)``.
        """
        return {key: (digest, row)
                for key, digest, row in zip(self.keys, self.digests, self.rows)}

    def matches(self, settings: EmbeddingSettings) -> bool:
        """Whether these vectors were made as the settings would make them.

        Args:
            settings: The embedding settings in force.

        Returns:
            True if provider, model and dimensions equal the settings', and
            the task type equals the model's when it takes one.
        """
        task = _document_task(settings)
        # Files from models that take no task may still record Gemini's.
        return (self.provider == settings.provider
                and self.model == settings.model
                and self.dimensions == settings.dimensions
                and (task is None or self.task_type == task))


def _document_task(settings: EmbeddingSettings) -> str | None:
    """The task the configured model embeds the book's sections as."""
    tasks = settings.model_provider.embedding_tasks(settings.model)
    return tasks.document if tasks else None


# --------------------------------------------------------------------------
# What gets embedded


def digest(text: str) -> str:
    """A short fingerprint of a text, for change detection only.

    Args:
        text: The text embedded.

    Returns:
        The first 16 hex characters of its SHA-256.
    """
    return sha256(text.encode("utf-8")).hexdigest()[:16]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0]


def texts(document: dict, max_chars: int = 6000,
          document_prefix: str = "") -> dict[str, str]:
    """The text to embed for each section with prose.

    Each is prefixed with its heading path (``Monsters > Goblin > Actions``),
    since dozens of sections share headings like "Actions".  Prefixed and
    truncated here, not in ``embed``, so the digest describes what was sent.

    Args:
        document: The stage 1 artifact.
        max_chars: Truncation limit, at a word boundary.
        document_prefix: Put before every text, for a model that asks for one.

    Returns:
        Section id to text.
    """
    found: dict[str, str] = {}

    def walk(node: dict, trail: list[str]) -> None:
        heading = (node.get("heading") or "").strip()
        here = trail + [heading] if heading else trail
        content = (node.get("content") or "").strip()
        if content:
            breadcrumb = " > ".join(here)
            whole = f"{breadcrumb}\n\n{content}" if breadcrumb else content
            found[node["id"]] = _truncate(document_prefix + whole, max_chars)
        for child in node.get("subsections") or []:
            walk(child, here)

    for root in document.get("sections") or []:
        walk(root, [])
    return found


# --------------------------------------------------------------------------
# The file


def write(path: Path, vectors: Vectors) -> Path:
    """Write vectors in the format described in the module docstring.

    Args:
        path: Destination; parent directories are created.
        vectors: What to write.

    Returns:
        ``path``.
    """
    header = json.dumps({
        "version": VERSION,
        "provider": vectors.provider,
        "model": vectors.model,
        "dimensions": vectors.dimensions,
        "dtype": "float32",
        "task_type": vectors.task_type,
        "normalised": True,
        "count": len(vectors),
        "created": date.today().isoformat(),
        "artifact": vectors.artifact,
        "keys": vectors.keys,
        "digests": vectors.digests,
    }, ensure_ascii=False).encode("utf-8")

    payload = array("f")
    for row in vectors.rows:
        payload.extend(row)
    if _SWAP:
        payload.byteswap()

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(MAGIC)
        handle.write(_HEADER_LENGTH.pack(len(header)))
        handle.write(header)
        payload.tofile(handle)
    return path


def read(path: Path) -> Vectors:
    """Read a file written by ``write``.

    Args:
        path: The ``.idx`` file.

    Returns:
        Its vectors and header fields.

    Raises:
        BadEmbeddingsFile: Wrong magic, another format version, an
            unreadable header, or a truncated payload.
    """
    with path.open("rb") as handle:
        if handle.read(len(MAGIC)) != MAGIC:
            raise BadEmbeddingsFile(f"{path} is not an embeddings file")
        packed = handle.read(_HEADER_LENGTH.size)
        if len(packed) != _HEADER_LENGTH.size:
            raise BadEmbeddingsFile(f"{path} is truncated: no header length")
        (length,) = _HEADER_LENGTH.unpack(packed)
        try:
            header = json.loads(handle.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BadEmbeddingsFile(f"{path} has an unreadable header") from exc

        version = header.get("version")
        if version != VERSION:
            raise BadEmbeddingsFile(
                f"{path} is format version {version}; this build reads "
                f"version {VERSION}")

        dimensions = int(header["dimensions"])
        keys = list(header["keys"])
        payload = array("f")
        try:
            payload.fromfile(handle, len(keys) * dimensions)
        except EOFError as exc:
            raise BadEmbeddingsFile(
                f"{path} is truncated: fewer than {len(keys)} vectors of "
                f"{dimensions} floats") from exc
        if _SWAP:
            payload.byteswap()

    flat = payload.tolist()
    rows = [flat[i * dimensions:(i + 1) * dimensions] for i in range(len(keys))]
    return Vectors(model=header["model"], dimensions=dimensions,
                   task_type=header.get("task_type"), keys=keys,
                   digests=list(header["digests"]), rows=rows,
                   artifact=header.get("artifact") or {},
                   provider=header.get("provider", Provider.GOOGLE))


# --------------------------------------------------------------------------
# The network


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def normalise(vector: Iterable[float]) -> list[float]:
    """Scale a vector to unit length.

    The API normalises only at the native 3072 dimensions.

    Args:
        vector: Any vector.

    Returns:
        The unit vector; a zero vector is returned unchanged.
    """
    values = list(vector)
    length = math.sqrt(sum(value * value for value in values))
    return [value / length for value in values] if length else values


def embed(batch: list[str], settings: EmbeddingSettings,
          report: Report = lambda _: None, *,
          query: bool = False) -> list[list[float]]:
    """Embed texts with the configured provider.

    Rate limits (as the provider words them) are retried with exponential
    backoff, up to ``ATTEMPTS`` attempts per batch.  Vectors are checked
    against ``settings.dimensions``, never cut to it: only some models keep
    their meaning when truncated.

    Args:
        batch: Texts to embed.
        settings: Provider, model, dimensions, batch size and key.
        report: Receives progress lines.
        query: Embed questions rather than the book's sections.

    Returns:
        One normalised vector per text, in order.

    Raises:
        MissingEmbeddings: No API key, the provider's package is not
            installed, or the model returns vectors of another width.
        RuntimeError: Rate limited ``ATTEMPTS`` times in a row.
        Exception: Any other provider error, unchanged.
    """
    variable = settings.missing_key()
    if variable:  # pragma: no cover - guarded upstream
        raise MissingEmbeddings(f"{variable} is not set")
    provider = settings.model_provider
    try:
        embed_chunk = provider.embedder(settings, query=query)
    except ImportError as exc:
        raise MissingEmbeddings(
            f"EMBED_PROVIDER={settings.provider} needs its package: run "
            f"`uv sync --extra {settings.provider}` in backend/") from exc

    out: list[list[float]] = []
    for chunk in _chunks(batch, settings.batch):
        for attempt in range(ATTEMPTS):
            try:
                vectors = embed_chunk(chunk)
                break
            except Exception as exc:  # each provider raises a family of these
                if not any(sign in str(exc) for sign in provider.rate_limited):
                    raise
                if attempt == ATTEMPTS - 1:
                    raise RuntimeError(
                        f"rate limited {ATTEMPTS} times in a row; try later"
                    ) from exc
                wait = 2 ** attempt
                report(f"  rate limited, retrying in {wait}s")
                time.sleep(wait)
        for vector in vectors:
            if len(vector) != settings.dimensions:
                raise MissingEmbeddings(
                    f"{settings.model} returns {len(vector)} dimensions, not "
                    f"{settings.dimensions}; set EMBED_DIMENSIONS="
                    f"{len(vector)}")
        out.extend(normalise(vector) for vector in vectors)
        report(f"  embedded {len(out)}/{len(batch)}")
    return out


# --------------------------------------------------------------------------
# The policy


def _made(provider: str, model: str, dimensions: int, task: str | None) -> str:
    """How a set of vectors is made, for a report line."""
    made = f"{provider} {model} at {dimensions}"
    return f"{made} ({task})" if task else made


def resolve(document: dict, *, path: Path, settings: EmbeddingSettings,
            refresh: bool = False, report: Report = lambda _: None,
            embedder: Callable[..., list[list[float]]] = embed) -> Vectors:
    """Every section's vector, from the file where its digest matches (under
    any id) and the API otherwise.  Writes the file back if anything was
    generated or renumbered.

    Args:
        document: The stage 1 artifact.
        path: The ``.idx`` file to read and write.
        settings: Embedding settings; a file made under others is ignored.
        refresh: Ignore the file and embed everything.
        report: Receives progress lines.
        embedder: Replaces ``embed`` in tests.

    Returns:
        A vector for every section with prose.

    Raises:
        MissingEmbeddings: Some sections lack a vector and there is no key.
        BadEmbeddingsFile: The file exists but cannot be read.
    """
    wanted = texts(document, settings.max_chars, settings.document_prefix)
    task = _document_task(settings)
    cached: dict[str, tuple[str, list[float]]] = {}

    if path.exists() and not refresh:
        stored = read(path)
        if stored.matches(settings):
            cached = stored.by_key()
            report(f"embeddings: read {len(cached)} from {path}")
        else:
            report(f"embeddings: ignoring {path}, which holds "
                   f"{_made(stored.provider, stored.model, stored.dimensions, stored.task_type)}, "
                   f"not {_made(settings.provider, settings.model, settings.dimensions, task)}")
    elif refresh:
        report("embeddings: refreshing, ignoring any cached file")

    # Section ids are positional, so a section added before others renumbers
    # them; a vector whose text is unchanged is reused under its new id.
    by_digest = {text_digest: row for text_digest, row in cached.values()}
    renumbered = 0
    for key, text in wanted.items():
        text_digest = digest(text)
        if cached.get(key, ("",))[0] != text_digest and text_digest in by_digest:
            cached[key] = (text_digest, by_digest[text_digest])
            renumbered += 1
    if renumbered:
        report(f"embeddings: {renumbered} reused under a new section id")

    missing = [key for key, text in wanted.items()
               if key not in cached or cached[key][0] != digest(text)]

    variable = settings.missing_key()
    if missing and variable:
        raise MissingEmbeddings(
            f"{len(missing)} of {len(wanted)} sections have no embedding and "
            f"{variable} is not set.\nEither set it and run "
            f"`uv run rules-lawyer embed`, or download {path.name} and point "
            f"RULES_LAWYER_EMBEDDINGS at it.")

    if missing:
        report(f"embeddings: {len(missing)} to generate with {settings.model}")
        fresh = embedder([wanted[key] for key in missing], settings, report)
        for key, row in zip(missing, fresh):
            cached[key] = (digest(wanted[key]), row)

    keys = list(wanted)
    vectors = Vectors(
        provider=settings.provider, model=settings.model, dimensions=settings.dimensions,
        task_type=task, keys=keys,
        digests=[cached[key][0] for key in keys],
        rows=[cached[key][1] for key in keys],
        artifact={k: v for k, v in (document.get("meta") or {}).items()
                  if k in ("pdf", "generated", "pages")})

    if missing or renumbered:
        write(path, vectors)
        report(f"embeddings: wrote {len(vectors)} to {path}")
    return vectors
