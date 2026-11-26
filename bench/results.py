"""The question set, and the JSONL files a run's answers and grades are kept in."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from rules_lawyer.config import get_settings

BENCH_DIR = Path(__file__).resolve().parent


def load_yaml(name: str) -> object:
    """A YAML file in ``bench/``, parsed.

    Args:
        name: The file's name, such as ``questions.yaml``.

    Returns:
        The parsed document; None for an empty file.
    """
    return yaml.safe_load((BENCH_DIR / name).read_text(encoding="utf-8"))


def run_dir(name: str) -> Path:
    """Where a run's files live: ``data/bench/<name>/``, created if missing.

    Args:
        name: The run's name.

    Returns:
        The directory.
    """
    path = get_settings().data_dir / "bench" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_jsonl(path: Path) -> list[dict]:
    """Every record in a JSONL file; none if it does not exist.

    Args:
        path: The file.

    Returns:
        The records, in file order.
    """
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines if line.strip()]


def append_jsonl(path: Path, record: dict) -> None:
    """Append one record, so a run interrupted later keeps it.

    Args:
        path: The file.
        record: A JSON-serialisable dict.
    """
    with path.open("a", encoding="utf-8") as lines:
        lines.write(json.dumps(record, ensure_ascii=False) + "\n")


def latest(records: list[dict]) -> list[dict]:
    """One record per (question, arm), the last appended, since a retried answer or grade is appended again.

    Args:
        records: Answers or grades, in file order.

    Returns:
        The surviving records, in order of each pair's first appearance.
    """
    return list({(record["question"], record["arm"]): record for record in records}.values())
