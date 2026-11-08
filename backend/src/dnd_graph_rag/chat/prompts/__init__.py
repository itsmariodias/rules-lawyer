"""
The prose the model is given, kept as markdown files beside this module.

Each file is exactly what the model receives, so a paragraph or a bullet is
one line however long it gets: a line break inside one would be sent as a
line break. The trailing newline an editor adds at the end of a file is the
only thing taken off.

The tool descriptions are not here. They are the docstrings in ``tools.py``,
because LangChain parses their ``Args:`` sections into each tool's
parameter schema, which makes them code as much as prose.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent


def prompt(name: str) -> str:
    """
    The prompt in ``<name>.md``.

    Read once, by the module that sends it, when that module is imported: an
    unknown name fails at startup rather than on the first turn that needed
    it.
    """
    return (HERE / f"{name}.md").read_text(encoding="utf-8").rstrip("\n")
