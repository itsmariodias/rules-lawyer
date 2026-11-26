"""Compare the graph agent with the whole SRD in the prompt, a smaller model and no retrieval.

Run from ``backend/``: ``uv run python ../bench/bench.py run | grade | report``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import asdict
from pathlib import Path

import yaml

# The dry run borrows the test suite's fake model.
sys.path.insert(1, str(Path(__file__).resolve().parent.parent / "backend"))

import arms
import grade
import report
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from results import append_jsonl, latest, load_yaml, read_jsonl, run_dir

from tests.fakes import FakeChatModel

DRY_RUN = "dry-run"


def main(argv: list[str] | None = None) -> None:
    """Parse the command line and run the command."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="answer the questions with each arm")
    run.add_argument("--run", default="pilot", help="the run's name (data/bench/<run>)")
    run.add_argument("--arms", default=",".join(arms.ARMS))
    run.add_argument("--question", type=int,
                     help="answer only this question, numbered from 1 in "
                          "questions.yaml; default all")
    run.add_argument("--dry-run", action="store_true",
                     help="fake models: the only API calls are a free token "
                          "count and the search's query embeddings; writes to "
                          "data/bench/dry-run")
    run.add_argument("--retry-errors", action="store_true",
                     help="answer again where the stored answer failed")

    judge = commands.add_parser("grade", help="score the answers")
    judge.add_argument("--run", default="pilot")
    judge.add_argument("--judge-provider", default="google")
    # A stronger model than any arm's, so the judge is not grading its own answers.
    judge.add_argument("--judge-model", default="gemini-3.1-pro-preview")
    judge.add_argument("--parallel", type=int, default=4, help="judge calls at a time")

    summary = commands.add_parser("report", help="write report.md and grading-sheet.md")
    summary.add_argument("--run", default="pilot")

    args = parser.parse_args(argv)
    if args.command == "run":
        asyncio.run(run_questions(args))
    elif args.command == "grade":
        asyncio.run(grade_answers(args))
    else:
        write_reports(args)


async def run_questions(args: argparse.Namespace) -> None:
    """Answer each question with each arm, one at a time, appending to answers.jsonl."""
    chosen_arms = args.arms.split(",")
    unknown = set(chosen_arms) - set(arms.ARMS)
    if unknown:
        raise SystemExit(f"no such arm: {', '.join(sorted(unknown))}")
    questions = load_yaml("questions.yaml")
    if args.question is not None:
        if not 1 <= args.question <= len(questions):
            raise SystemExit(f"--question must be from 1 to {len(questions)}")
        questions = [questions[args.question - 1]]
    folder = run_dir(DRY_RUN if args.dry_run else args.run)
    answers_path = folder / "answers.jsonl"
    if args.dry_run:
        answers_path.unlink(missing_ok=True)

    stored = read_jsonl(answers_path)
    done = {(answer["question"], answer["arm"]) for answer in stored
            if not (args.retry_errors and answer["error"])}

    document = arms.srd_with_ids() if "full-srd" in chosen_arms else None
    if args.dry_run and document is not None:
        try:
            counted = arms.chat_model(arms.model_name("full-srd")).get_num_tokens(
                arms.system_prompt("full-srd", document))
            print(f"full-srd prompt: {counted:,} tokens per question, "
                  f"{counted * len(questions):,} for {len(questions)} questions "
                  "(before any caching)")
        except arms.ModelUnavailable as exc:
            print(f"full-srd prompt not counted: {exc}")

    for arm in chosen_arms:
        model = None
        for question in questions:
            if (question["id"], arm) in done:
                continue
            if model is None:
                if args.dry_run and arm in arms.AGENT_ARMS:
                    model = FakeChatModel()
                elif args.dry_run:
                    model = GenericFakeChatModel(messages=iter(
                        AIMessage(content=f"A fake answer to {item['id']}, citing "
                                          "[11.2.114].")
                        for item in questions))
                else:
                    model = arms.chat_model(arms.model_name(arm))

            if arm in arms.AGENT_ARMS:
                answer = await arms.answer_with_tools(question, arm, model)
            else:
                system = arms.system_prompt(arm, document if arm == "full-srd" else None)
                answer = await arms.answer_without_tools(question, arm, model, system)
            append_jsonl(answers_path, asdict(answer))
            print(f"{arm:13} {question['id']:22} {answer.wall_seconds:6.1f}s "
                  f"in {answer.usage.get('input', 0):>9,} "
                  f"cached {answer.usage.get('cached', 0):>9,} "
                  f"out {answer.usage.get('output', 0):>6,} "
                  f"thinking {answer.usage.get('reasoning', 0):>6,} "
                  f"tools {len(answer.tool_calls)}"
                  + (f"  ERROR {answer.error}" if answer.error else ""))
    print(f"answers: {answers_path}")


async def grade_answers(args: argparse.Namespace) -> None:
    """Score every answer not yet graded, appending to grades.jsonl."""
    folder = run_dir(args.run)
    questions = {question["id"]: question for question in load_yaml("questions.yaml")}
    grades_path = folder / "grades.jsonl"
    # A grade is redone when it failed, or when its answer was answered again.
    answered_at = {(answer["question"], answer["arm"]): index for index, answer
                   in enumerate(read_jsonl(folder / "answers.jsonl"))}
    graded = {(item["question"], item["arm"]) for item in read_jsonl(grades_path)
              if not item.get("error")
              and item.get("answer_index") == answered_at.get((item["question"], item["arm"]))}
    texts = grade.section_texts()
    pending = [answer for answer in latest(read_jsonl(folder / "answers.jsonl"))
               if (answer["question"], answer["arm"]) not in graded]
    model = (grade.judge_model(args.judge_provider, args.judge_model)
             if any(answer["text"].strip() and not answer["error"] for answer in pending)
             else None)
    # Judge calls are independent and untimed, so several run at once.
    running = asyncio.Semaphore(args.parallel)

    async def grade_one(answer: dict) -> bool:
        question = questions[answer["question"]]
        record = {"question": answer["question"], "arm": answer["arm"],
                  "answer_index": answered_at[(answer["question"], answer["arm"])],
                  "citation_check": grade.citation_scores(
                      answer["cited"], question["gold_sections"], texts)}
        if answer["error"] or not answer["text"].strip():
            record["score"] = 0.0
        else:
            cited = {section_id: texts[section_id]
                     for section_id in dict.fromkeys(answer["cited"]) if section_id in texts}
            async with running:
                try:
                    record |= await grade.judge(model, question, answer["text"], cited)
                except Exception as exc:  # noqa: BLE001 - recorded, and retried by the next grade
                    record["error"] = f"{type(exc).__name__}: {exc}"[:300]
        append_jsonl(grades_path, record)
        print(f"{answer['arm']:13} {answer['question']:22} "
              f"score {record.get('score', 'n/a')}"
              + (f"  ERROR {record['error']}" if record.get("error") else ""))
        return "error" not in record

    succeeded = await asyncio.gather(*(grade_one(answer) for answer in pending))
    failed = succeeded.count(False)
    if failed:
        print(f"{failed} not graded; run grade again to retry them")
    print(f"grades: {grades_path}")


def write_reports(args: argparse.Namespace) -> None:
    """Write report.md and grading-sheet.md for a run."""
    folder = run_dir(args.run)
    questions = load_yaml("questions.yaml")
    answers = latest(read_jsonl(folder / "answers.jsonl"))
    grades = latest(read_jsonl(folder / "grades.jsonl"))
    overrides_path = folder / "overrides.yaml"
    overrides = (yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
                 if overrides_path.exists() else None) or {}

    (folder / "report.md").write_text(report.write_report(
        questions, answers, grades, overrides, load_yaml("prices.yaml") or {},
        list(arms.ARMS)), encoding="utf-8")
    (folder / "grading-sheet.md").write_text(
        report.write_grading_sheet(questions, answers, grades), encoding="utf-8")
    print(f"report: {folder / 'report.md'}\nsheet:  {folder / 'grading-sheet.md'}")


if __name__ == "__main__":
    main()
