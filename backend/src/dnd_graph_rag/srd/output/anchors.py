"""The anchors file: where each rendered part of the markdown is printed on the page.

Written beside the markdown (``srd_hierarchy.anchors.json``), in document
order: ``{"start", "end", "boxes"}`` per part, a box per printed line. The
geometry stays out of the JSON and the graph; the side panel reads it to box
a citation on its page.
"""

from __future__ import annotations

import bisect
from dataclasses import asdict

from dnd_graph_rag.srd.model import Printed, Section
from dnd_graph_rag.srd.sections import walk


def anchors(parts: list[tuple[int, int, Printed]]) -> list[dict]:
    """The anchors for rendered parts: each one's span and its lines' boxes.

    Args:
        parts: The parts ``render_book`` returns, in document order.

    Returns:
        One anchor per part with boxes; a float's heading has none, its lines
        being its block's.
    """
    return [{"start": start, "end": end, "boxes": [asdict(box) for box in part.boxes]}
            for start, end, part in parts if part.boxes]


def misplaced(sections: list[Section], anchors: list[dict]) -> list[str]:
    """Each section with no boxes in its span, or a box on a page outside its page range.

    The pages come from the blocks and the boxes from the lines, so a
    disagreement is a defect in one of them.
    """
    starts = [anchor["start"] for anchor in anchors]
    found: list[str] = []
    for section in walk(sections):
        source = section.source
        first = max(0, bisect.bisect_left(starts, source.char_start) - 1)
        pages = {box["page"] for anchor in anchors[first:bisect.bisect_left(starts, source.char_end)]
                 if anchor["end"] > source.char_start for box in anchor["boxes"]}
        if not pages:
            found.append(f"Anchors: {section.id} {section.heading} has no boxes")
        elif not pages <= set(range(source.page_start, source.page_end + 1)):
            found.append(f"Anchors: {section.id} {section.heading} has boxes on pages {sorted(pages)}, "
                         f"outside {source.page_start}-{source.page_end}")
    return found
