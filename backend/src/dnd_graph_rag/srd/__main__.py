"""Extract the SRD to JSON, then render the markdown from that JSON.

Usage: ``uv run python -m dnd_graph_rag.srd``. Writes
``data/output/srd_hierarchy.json``, and ``srd_hierarchy.md`` and its page
anchors (``srd_hierarchy.anchors.json``) beside it, then exits non-zero if the
book disagrees with itself anywhere it is checked, other than in its known
quirks. The markdown is rendered again from the JSON as written, and must be
the markdown its offsets were taken from.
"""

from __future__ import annotations

import json
import sys

from ..config import anchors_path_for, get_settings, markdown_path_for
from .build import build
from .output.document import from_json
from .output.render import render_book
from .verify import KNOWN


def main() -> None:
    """Build the artifact, write it, and report what the book disagrees with itself on."""
    settings = get_settings()
    json_path = settings.output_path
    md_path = markdown_path_for(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)

    artifact = build(settings.pdf_path, md_path.name)
    json_path.write_text(json.dumps(artifact.document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rendered, _, _ = render_book(*from_json(json.loads(json_path.read_text(encoding="utf-8"))))
    if rendered != artifact.markdown:
        raise RuntimeError("the JSON read back renders other markdown than its offsets were taken from")
    md_path.write_text(rendered, encoding="utf-8")
    anchors_path = anchors_path_for(md_path)
    anchors_path.write_text(json.dumps(artifact.anchors), encoding="utf-8")
    print(f"{json_path}\n{md_path}\n{anchors_path}")

    for message in artifact.problems:
        print(f"known quirk: {message}" if message in KNOWN else message)
    if set(artifact.problems) - KNOWN:
        sys.exit(1)
    print("The book agrees with itself, but for its known quirks.")


if __name__ == "__main__":
    main()
