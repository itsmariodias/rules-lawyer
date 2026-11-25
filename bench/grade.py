"""Grade answers: citations against the gold sections, facts by a judge model.

The judge never sees which arm wrote an answer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection

from arms import usage_of
from langchain_core.messages import HumanMessage, SystemMessage
from results import BENCH_DIR

from rules_lawyer.chat.agent.model import ModelUnavailable
from rules_lawyer.config import ChatSettings, get_settings

JUDGE_PROMPT = (BENCH_DIR / "prompts" / "judge.md").read_text(encoding="utf-8").rstrip("\n")
VERDICTS = {"present", "absent", "contradicted"}
# A cited section is shown to the judge up to this many characters: a cited
# chapter would otherwise be hundreds of thousands (Monsters A-Z is 87 pages).
CITED_SECTION_CHARS = 6000


def section_texts() -> dict[str, str]:
    """Every section in the artifact, as a citation of it shows: its markdown, subsections included.

    Returns:
        ``{id: text}``, each text cut to ``CITED_SECTION_CHARS``.
    """
    settings = get_settings()
    markdown = settings.output_path.with_suffix(".md").read_text(encoding="utf-8")
    document = json.loads(settings.output_path.read_text(encoding="utf-8"))
    texts = {}
    stack = list(document["sections"])
    while stack:
        section = stack.pop()
        text = markdown[section["source"]["char_start"]:section["source"]["char_end"]]
        if len(text) > CITED_SECTION_CHARS:
            text = text[:CITED_SECTION_CHARS] + "\n(cut here; the section continues)"
        texts[section["id"]] = text
        stack.extend(section["subsections"])
    return texts


def citation_scores(cited: list[str], gold: list[str], known: Collection[str]) -> dict:
    """Which of the sections stating the answer were cited, and which citations are of no section.

    A citation of a gold section's ancestor or descendant counts, since a
    section's text covers its subsections. Whether each citation supports
    its claim is the judge's to say (``judge``).

    Args:
        cited: The ids the answer cites, repeats included.
        gold: The question's gold sections.
        known: Every id in the artifact.

    Returns:
        ``cited`` (distinct ids), ``recall`` (gold sections some citation
        relates to; None if there are none) and ``invented`` (cited ids that
        are no section).
    """
    def related(one: str, other: str) -> bool:
        return (one == other or one.startswith(other + ".")
                or other.startswith(one + "."))

    distinct = list(dict.fromkeys(cited))
    gold_hit = [gold_id for gold_id in gold
                if any(related(cited_id, gold_id) for cited_id in distinct)]
    return {
        "cited": len(distinct),
        "recall": len(gold_hit) / len(gold) if gold else None,
        "invented": [cited_id for cited_id in distinct if cited_id not in known],
    }


def judge_model(provider: str, model: str):
    """Build the judge.

    Args:
        provider: A ``CHAT_PROVIDER`` value, such as ``google``.
        model: The model id.

    Returns:
        The chat model.

    Raises:
        ModelUnavailable: The provider's key is not set.
    """
    settings = ChatSettings(provider=provider, model=model)
    variable = settings.missing_key()
    if variable:
        raise ModelUnavailable(f"{variable} is not set, so the judge cannot run")
    return settings.model_provider.chat(settings)


async def judge(model, question: dict, answer_text: str,
                cited_sections: dict[str, str]) -> dict:
    """Ask the judge to mark each gold fact, known wrong answer and citation.

    Args:
        model: The judge (``judge_model``).
        question: A question from ``questions.yaml``.
        answer_text: The answer to grade.
        cited_sections: The text of each real section the answer cites, by id.

    Returns:
        ``facts``, ``wrong_answers``, ``other_errors``, ``citations`` (each
        cited id, whether its section supports what the answer attaches it
        to), ``citation_accuracy`` (supported over cited; None if nothing
        is cited), the judge's ``usage``, and ``score``: facts present over
        facts, or 0 if any fact is contradicted or a known wrong answer
        stated.

    Raises:
        ValueError: The reply is not the JSON asked for, or marks another
            number of facts, or other citations, than it was given.
    """
    facts = "\n".join(f"{number}. {fact}"
                      for number, fact in enumerate(question["gold_facts"], start=1))
    wrong = "\n".join(f"- {item}" for item in question["must_not"]) or "(none)"
    sections = "\n".join(f'<section id="{section_id}">\n{text}\n</section>'
                         for section_id, text in cited_sections.items()) or "(none)"
    prompt = (f"Question: {question['question']}\n\nKey facts:\n{facts}\n\n"
              f"Known wrong answers:\n{wrong}\n\n"
              f"Answer to grade:\n<answer>\n{answer_text}\n</answer>\n\n"
              f"Sections the answer cites:\n{sections}")

    reply = await model.ainvoke([SystemMessage(content=JUDGE_PROMPT),
                                 HumanMessage(content=prompt)])
    # Models asked for bare JSON still wrap it in a code fence at times.
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.text.strip())
    try:
        verdict = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"the judge did not reply with JSON: {raw[:200]}") from exc

    marks = [fact.get("verdict") for fact in verdict.get("facts", [])]
    if len(marks) != len(question["gold_facts"]) or not set(marks) <= VERDICTS:
        raise ValueError(f"the judge marked {marks} for {len(question['gold_facts'])} facts")
    wrong_stated = [item for item in verdict.get("wrong_answers", []) if item.get("stated")]
    citations = verdict.get("citations", [])
    if sorted(item.get("id") for item in citations) != sorted(cited_sections):
        raise ValueError(f"the judge marked citations {[item.get('id') for item in citations]} "
                         f"for {list(cited_sections)}")

    if "contradicted" in marks or wrong_stated:
        score = 0.0
    else:
        score = marks.count("present") / len(marks)
    return {
        "facts": verdict["facts"],
        "wrong_answers": verdict.get("wrong_answers", []),
        "other_errors": verdict.get("other_errors", []),
        "citations": citations,
        "citation_accuracy": (sum(1 for item in citations if item.get("supported"))
                              / len(citations) if citations else None),
        "usage": usage_of([reply]),
        "score": score,
    }
