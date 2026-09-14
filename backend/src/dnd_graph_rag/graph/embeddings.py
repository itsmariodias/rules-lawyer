"""
The dense half of retrieval: one vector per section, and the file that makes
generating them somebody else's problem.

Embedding the book is a one-time activity, since the text changes only when
``srd-parse`` changes, so it belongs to the load rather than to the chat.
But it costs an API key, and everything else here runs on a PDF and Docker
alone.  So the vectors are also a *file*: ``srd_embeddings.idx``, which a
reader downloads, points ``DND_GRAPH_RAG_EMBEDDINGS`` at, and loads without
ever calling Google.

**Embeddings are required, not an enrichment.**  Either they are generated or
they are supplied; a load that can do neither raises :class:`MissingEmbeddings`
rather than quietly writing a graph with a hole in it.  That exception's
message is most of this module's user interface, so it names both ways out.

Nothing here imports a driver.  Like ``mapping``, the whole of it is a
function of the document and is tested without a database; the one call that
touches the network is injectable, so it is tested without a key either.
"""

from __future__ import annotations

import json
import math
import struct
import sys
import time
from array import array
from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Callable, Iterable, Iterator

from ..config import EmbeddingSettings

Report = Callable[[str], None]

# ``DNDEMB`` plus a format version, so a file written by a later version is
# refused by name rather than read as garbage.
MAGIC = b"DNDEMB\x00"
VERSION = 1
_HEADER_LENGTH = struct.Struct("<I")
# The payload is fixed little-endian, so a file moves between machines.
_SWAP = sys.byteorder != "little"


class MissingEmbeddings(RuntimeError):
    """No vectors for some sections, and no way to generate them."""


class BadEmbeddingsFile(ValueError):
    """The file is not one of ours, or is truncated."""


@dataclass(slots=True)
class Vectors:
    """
    Every section's embedding, plus what was embedded to get it.

    ``keys``, ``digests`` and ``rows`` are parallel: row *i* is the embedding
    of the text whose digest is ``digests[i]``, for the section ``keys[i]``.
    The digests are what make this a cache as well as an artifact: a re-parse
    that changed twelve sections re-embeds twelve sections.
    """

    model: str
    dimensions: int
    task_type: str
    keys: list[str]
    digests: list[str]
    rows: list[list[float]]
    artifact: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.keys)

    def by_key(self) -> dict[str, tuple[str, list[float]]]:
        return {key: (digest, row)
                for key, digest, row in zip(self.keys, self.digests, self.rows)}

    def matches(self, settings: EmbeddingSettings) -> bool:
        """Whether this file was made in the space the settings ask for."""
        return (self.model == settings.model
                and self.dimensions == settings.dimensions
                and self.task_type == settings.task_type)


# --------------------------------------------------------------------------
# What gets embedded


def digest(text: str) -> str:
    """Enough of a hash to notice an edit; not a security boundary."""
    return sha256(text.encode("utf-8")).hexdigest()[:16]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0]


def texts(document: dict, max_chars: int = 6000) -> dict[str, str]:
    """
    One text per section that has prose, keyed by section id.

    The ancestor headings lead, because a heading on its own is routinely
    meaningless: the book has dozens of sections called "Traits" and
    "Actions", and the tree is the only thing that tells them apart.  A
    stat block's "Actions" embedded bare is noise; embedded as
    ``Monsters > Goblin > Actions`` it is the thing someone is searching for.

    Truncation happens here rather than in ``embed`` so that the digest
    describes what was actually sent.
    """
    found: dict[str, str] = {}

    def walk(node: dict, trail: list[str]) -> None:
        heading = (node.get("heading") or "").strip()
        here = trail + [heading] if heading else trail
        content = (node.get("content") or "").strip()
        if content:
            breadcrumb = " > ".join(here)
            whole = f"{breadcrumb}\n\n{content}" if breadcrumb else content
            found[node["id"]] = _truncate(whole, max_chars)
        for child in node.get("subsections") or []:
            walk(child, here)

    for root in document.get("sections") or []:
        walk(root, [])
    return found


# --------------------------------------------------------------------------
# The file


def write(path: Path, vectors: Vectors) -> Path:
    """
    Magic, a JSON header, then the payload as raw little-endian float32.

    Nothing but the standard library: ``array.tolist()`` is already the
    ``list[float]`` the Neo4j driver wants, so numpy would buy a dependency
    and no conversion.
    """
    header = json.dumps({
        "version": VERSION,
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
    """The inverse.  A file that is not ours fails by name, not by garbage."""
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
                   task_type=header["task_type"], keys=keys,
                   digests=list(header["digests"]), rows=rows,
                   artifact=header.get("artifact") or {})


# --------------------------------------------------------------------------
# The network


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def normalise(vector: Iterable[float]) -> list[float]:
    """
    Unit length, which the API guarantees only at the model's native 3072.

    Cosine similarity over unnormalised truncated vectors is still defined,
    but Neo4j's cosine index and every dot product downstream assume this.
    """
    values = list(vector)
    length = math.sqrt(sum(value * value for value in values))
    return [value / length for value in values] if length else values


def embed(batch: list[str], settings: EmbeddingSettings,
          report: Report = lambda _: None) -> list[list[float]]:
    """
    The only call that reaches Google.  Injectable, so ``resolve`` is tested
    without a key.

    A 429 is retried rather than fatal: the free tier's per-minute limit is
    reached well before its daily one, and failing a twenty-minute run on a
    rate limit would be absurd.
    """
    from google import genai
    from google.genai import types

    if settings.google_api_key is None:  # pragma: no cover - guarded upstream
        raise MissingEmbeddings("GOOGLE_API_KEY is not set")

    client = genai.Client(api_key=settings.google_api_key.get_secret_value())
    config = types.EmbedContentConfig(
        task_type=settings.task_type,
        output_dimensionality=settings.dimensions)

    out: list[list[float]] = []
    for index, chunk in enumerate(_chunks(batch, settings.batch)):
        for attempt in range(5):
            try:
                response = client.models.embed_content(
                    model=settings.model, contents=chunk, config=config)
                break
            except Exception as exc:  # the SDK raises a family of these
                if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc):
                    raise
                wait = 2 ** attempt
                report(f"  rate limited, retrying in {wait}s")
                time.sleep(wait)
        else:  # pragma: no cover - only on a sustained rate limit
            raise RuntimeError("rate limited five times in a row; try later")
        out.extend(normalise(item.values) for item in response.embeddings)
        report(f"  embedded {len(out)}/{len(batch)}")
    return out


# --------------------------------------------------------------------------
# The policy


def resolve(document: dict, *, path: Path, settings: EmbeddingSettings,
            refresh: bool = False, report: Report = lambda _: None,
            embedder: Callable[..., list[list[float]]] = embed) -> Vectors:
    """
    Every section's vector, from the file where possible and the API where
    not.  Complete, or :class:`MissingEmbeddings`.

    Nothing downstream has to reason about a partial set, which is the point:
    the check in ``verify`` is then a real one rather than a tautology.
    """
    wanted = texts(document, settings.max_chars)
    cached: dict[str, tuple[str, list[float]]] = {}

    if path.exists() and not refresh:
        stored = read(path)
        if stored.matches(settings):
            cached = stored.by_key()
            report(f"embeddings: read {len(cached)} from {path}")
        else:
            report(f"embeddings: ignoring {path}, which holds "
                   f"{stored.model} at {stored.dimensions} "
                   f"({stored.task_type}), not {settings.model} at "
                   f"{settings.dimensions} ({settings.task_type})")
    elif refresh:
        report("embeddings: refreshing, ignoring any cached file")

    missing = [key for key, text in wanted.items()
               if key not in cached or cached[key][0] != digest(text)]

    if missing and settings.google_api_key is None:
        raise MissingEmbeddings(
            f"{len(missing)} of {len(wanted)} sections have no embedding and "
            f"GOOGLE_API_KEY is not set.\nEither set it and run "
            f"`uv run srd-embed`, or download {path.name} and point "
            f"DND_GRAPH_RAG_EMBEDDINGS at it.")

    if missing:
        report(f"embeddings: {len(missing)} to generate with {settings.model}")
        fresh = embedder([wanted[key] for key in missing], settings, report)
        for key, row in zip(missing, fresh):
            cached[key] = (digest(wanted[key]), row)

    keys = list(wanted)
    vectors = Vectors(
        model=settings.model, dimensions=settings.dimensions,
        task_type=settings.task_type, keys=keys,
        digests=[cached[key][0] for key in keys],
        rows=[cached[key][1] for key in keys],
        artifact={k: v for k, v in (document.get("meta") or {}).items()
                  if k in ("pdf", "generated", "pages")})

    if missing:
        write(path, vectors)
        report(f"embeddings: wrote {len(vectors)} to {path}")
    return vectors
