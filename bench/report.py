"""A run's answers and grades as tables per arm and per category, and a sheet for checking the judge."""

from __future__ import annotations

from collections import defaultdict
from statistics import mean, median

PER_MILLION = 1_000_000


def cost(usage: dict, prices: dict | None) -> tuple[float | None, float | None]:
    """What a call's tokens cost, as billed and as if nothing had been cached.

    Args:
        usage: ``{"input", "cached", "output"}``, input including cached.
        prices: USD per million tokens: ``input``, ``cached_input``,
            ``output``; None if the model has no prices.

    Returns:
        ``(billed, uncached)``, each None if a price it needs is missing.
    """
    if not prices or prices.get("input") is None or prices.get("output") is None:
        return None, None
    uncached = (usage["input"] * prices["input"]
                + usage["output"] * prices["output"]) / PER_MILLION
    if prices.get("cached_input") is None:
        return None, uncached
    billed = ((usage["input"] - usage["cached"]) * prices["input"]
              + usage["cached"] * prices["cached_input"]
              + usage["output"] * prices["output"]) / PER_MILLION
    return billed, uncached


def _number(value: float | None, digits: int = 2) -> str:
    """A table cell: the value rounded, or n/a."""
    return "n/a" if value is None else f"{value:,.{digits}f}"


def _mean(values: list) -> float | None:
    """The mean of the values that are not None, or None if there are none."""
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def write_report(questions: list[dict], answers: list[dict], grades: list[dict],
                 overrides: dict, prices: dict, arms: list[str]) -> str:
    """The run's results as markdown.

    Args:
        questions: The question set.
        answers: The run's answers.
        grades: Their grades.
        overrides: Scores set by hand, ``{question: {arm: score}}``; they
            win over the judge's.
        prices: USD per million tokens, by model id.
        arms: The arms to report, in column order.

    Returns:
        The report.
    """
    category_of = {question["id"]: question["category"] for question in questions}
    grade_of = {(grade["question"], grade["arm"]): grade for grade in grades}

    def score(question_id: str, arm: str) -> float | None:
        manual = (overrides.get(question_id) or {}).get(arm)
        if manual is not None:
            return float(manual)
        grade = grade_of.get((question_id, arm))
        return grade.get("score") if grade else None

    rows = []
    by_category: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for arm in arms:
        done = [answer for answer in answers if answer["arm"] == arm]
        if not done:
            continue
        scores, accuracies, recalls, invented = [], [], [], 0
        billed_total, uncached_total = 0.0, 0.0
        has_billed, has_uncached = True, True
        for answer in done:
            question_score = score(answer["question"], arm)
            scores.append(question_score)
            by_category[category_of[answer["question"]]][arm].append(question_score)
            grade = grade_of.get((answer["question"], arm)) or {}
            check = grade.get("citation_check") or {}
            accuracies.append(grade.get("citation_accuracy"))
            recalls.append(check.get("recall") if check.get("cited") else None)
            invented += len(check.get("invented", []))
            billed, uncached = cost(answer["usage"] or {"input": 0, "cached": 0, "output": 0},
                                    prices.get(answer["model"]))
            has_billed &= billed is not None
            has_uncached &= uncached is not None
            billed_total += billed or 0
            uncached_total += uncached or 0
        first_tokens = [answer["first_token_seconds"] for answer in done
                        if answer["first_token_seconds"] is not None]
        walls = [answer["wall_seconds"] for answer in done]
        rows.append([
            f"{arm}", f"{done[0]['model']} ({done[0].get('thinking', 'default')} thinking)",
            str(len(done)),
            str(sum(1 for answer in done if answer["error"])),
            _number(_mean(scores)), _number(_mean(accuracies)), _number(_mean(recalls)),
            str(invented),
            f"{sum(answer['usage'].get('input', 0) for answer in done):,}",
            f"{sum(answer['usage'].get('cached', 0) for answer in done):,}",
            f"{sum(answer['usage'].get('output', 0) for answer in done):,}",
            f"{sum(answer['usage'].get('reasoning', 0) for answer in done):,}",
            _number(billed_total if has_billed else None, 4),
            _number(uncached_total if has_uncached else None, 4),
            str(sum(answer["usage"].get("calls", 0) for answer in done)),
            str(sum(len(answer["tool_calls"]) for answer in done)),
            _number(median(first_tokens) if first_tokens else None, 1),
            _number(median(walls), 1), _number(max(walls), 1),
        ])

    header = ["Arm", "Model", "Answers", "Errors", "Score", "Cite accuracy",
              "Cite recall", "Invented ids", "Input tokens", "Cached",
              "Output tokens", "Of which thinking", "Cost $", "Uncached cost $", "Model calls",
              "Tool calls", "First token s (median)", "Wall s (median)",
              "Wall s (max)"]
    lines = ["# Benchmark", "", ("Scores are facts present over facts, 0 on a "
             "contradiction or a known wrong answer; means over the questions "
             "answered. Cite accuracy is cited sections that support the claim they are attached to, as the judge reads them; cite recall is the key's sections cited; both are over answers that cite."), "",
             "## By arm", "", _table(header, rows), "", "## Score by category", ""]

    shown = [arm for arm in arms if any(answer["arm"] == arm for answer in answers)]
    category_rows = [[category] + [_number(_mean(by_category[category][arm])) for arm in shown]
                     for category in dict.fromkeys(category_of.values())]
    lines.append(_table(["Category", *shown], category_rows))
    return "\n".join(lines) + "\n"


def write_grading_sheet(questions: list[dict], answers: list[dict],
                        grades: list[dict]) -> str:
    """Every answer beside the judge's verdicts, question by question, for a spot check.

    Args:
        questions: The question set.
        answers: The run's answers.
        grades: Their grades.

    Returns:
        The sheet as markdown.
    """
    grade_of = {(grade["question"], grade["arm"]): grade for grade in grades}
    lines = ["# Grading sheet", "",
             ("Disagree with the judge? Put the score in `overrides.yaml` "
             "(`question-id: {arm: score}`) and run `report` again."), ""]
    for question in questions:
        lines += [f"## {question['id']} ({question['category']})", "",
                  f"**{question['question']}**", "", "Key:", ""]
        lines += [f"{number}. {fact}"
                  for number, fact in enumerate(question["gold_facts"], start=1)]
        lines += [""] + [f"- Wrong: {item}" for item in question["must_not"]] + [""]
        for answer in (answer for answer in answers if answer["question"] == question["id"]):
            grade = grade_of.get((question["id"], answer["arm"])) or {}
            lines += [f"### {answer['arm']}: score {_number(grade.get('score'))}", ""]
            if answer["error"]:
                lines += [f"Error: {answer['error']}", ""]
            lines += ["> " + line for line in (answer["text"] or "(no answer)").splitlines()]
            lines.append("")
            for number, fact in enumerate(grade.get("facts", []), start=1):
                lines.append(f"- {number}: {fact.get('verdict')} ({fact.get('note', '')})")
            for item in grade.get("wrong_answers", []):
                if item.get("stated"):
                    lines.append(f"- Wrong answer stated: {item.get('wrong')}")
            for item in grade.get("citations", []):
                if not item.get("supported"):
                    lines.append(f"- Citation [{item.get('id')}] does not support its claim "
                                 f"({item.get('note', '')})")
            for error in grade.get("other_errors", []):
                lines.append(f"- Other error: {error}")
            if grade.get("error"):
                lines.append(f"- Judge failed: {grade['error']}")
            lines.append("")
    return "\n".join(lines)


def _table(header: list[str], rows: list[list[str]]) -> str:
    """A markdown table."""
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)
