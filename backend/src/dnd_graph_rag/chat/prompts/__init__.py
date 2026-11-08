"""
Prompt files sent to the model verbatim.

Keep each paragraph on one line: a line break in a file is a line break
the model receives.  Tool descriptions live in ``tools.py`` docstrings.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent


def prompt(name: str) -> str:
    """
    Read ``<name>.md`` beside this module.  Called at import time, so a
    misspelt name fails at startup.

    Args:
        name: File stem, e.g. ``"system"``.

    Returns:
        The file's text without trailing newlines.

    Raises:
        FileNotFoundError: No such prompt.
    """
    return (HERE / f"{name}.md").read_text(encoding="utf-8").rstrip("\n")
