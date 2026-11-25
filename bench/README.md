# Bench

Twelve SRD rules questions answered four ways, scored on correctness,
citations, tokens, cost and time.

| Arm | Model | Gets |
| --- | --- | --- |
| `graph` | the configured chat model | the app's tools and prompt |
| `graph-lite` | `gemini-3.5-flash-lite` | the same tools and prompt |
| `full-srd` | the configured chat model | the whole rendered SRD (markdown) in the prompt, no tools |
| `closed-book` | the configured chat model | no tools and no document |

Run from `backend/`, with Neo4j loaded (`docker compose up -d neo4j`):

```bash
uv run python ../bench/bench.py run --dry-run      # fake models; costs only query embeddings
uv run python ../bench/bench.py run --question 1   # just the first question
uv run python ../bench/bench.py run                # the rest; done pairs are skipped
uv run python ../bench/bench.py grade              # judged by gemini-3.1-pro-preview
uv run python ../bench/bench.py report
```

Everything a run writes is in `data/bench/<run>/` (`--run`, default `pilot`):
`answers.jsonl`, `grades.jsonl`, `report.md` and `grading-sheet.md`. Read the
sheet, and put any score you disagree with in `overrides.yaml` there
(`question-id: {arm: score}`) before running `report` again.

`questions.yaml` holds each question's key: the facts a right answer states,
the sections stating them, and the wrong answers worth catching. A score is
facts present over facts, and 0 if the answer contradicts the key. Costs need
`prices.yaml` filled in.
