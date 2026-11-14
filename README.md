# Rules Lawyer

[![CI](https://github.com/itsmariodias/rules-lawyer/actions/workflows/ci.yml/badge.svg)](https://github.com/itsmariodias/rules-lawyer/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/itsmariodias/rules-lawyer/graph/badge.svg)](https://codecov.io/gh/itsmariodias/rules-lawyer)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![Node 22](https://img.shields.io/badge/node-22-5FA04E?logo=nodedotjs&logoColor=white)
![Neo4j 5.26](https://img.shields.io/badge/neo4j-5.26-4581C3?logo=neo4j&logoColor=white)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE.md)

Every table has one: the player who stops the game to ask whether you can
really grapple a gelatinous cube. Rules Lawyer is that player, except it
brings the book.

Ask it a rules question and it answers from the D&D 5e System Reference
Document (SRD 5.2.1), never from memory, and cites the passage behind every
claim. Click a citation and the printed page opens beside the answer, with
the lines it relied on highlighted. When the answer leads somewhere else (a
spell imposes a condition, a creature is immune to it, a class grants the
spell), you can follow the thread through the graph of how the rules connect.

Under the hood it is knowledge-graph RAG: the 364-page SRD PDF is parsed
into typed entities (spells, creatures, conditions, classes, items, rules)
and the relationships between them, loaded into Neo4j with embeddings, and
searched by a tool-calling agent.

## Features

- **Cited answers.** Every claim carries a citation to the SRD section it
  came from; invented citations are dropped, not shown.
- **The page, not a summary.** A citation opens the actual PDF page in a side
  panel with the cited lines boxed, plus a breadcrumb to where it sits in the
  book.
- **A graph to explore.** A second tab draws the cited section's
  neighbourhood (what it references, imposes, grants or is immune to), and
  any node can be expanded or opened on the page.
- **Search by words and by meaning.** Full-text and vector search, fused, so
  exact terms ("Fire damage") match exactly and a question that shares no
  words with the book still finds the passage it is asking about.
- **Exhaustive questions.** For "which creatures can Frighten?", the agent
  writes read-only Cypher against the graph instead of guessing from a few
  passages.
- **A book that checks itself.** Parsing cross-checks the SRD against its own
  stat block index, damage dice, attack bonuses and class spell lists, and
  loading verifies the graph against the parsed document.
- **Conversations that keep.** Threads are saved, pinnable and titled, and
  the last question can be retried.

[GRAPH.md](GRAPH.md) documents every node label and relationship type.

## Quickstart

You need **Python 3.12+** with [uv](https://docs.astral.sh/uv/),
**Node 22+**, **Docker**, and a **Gemini API key**.

Copy the example environment file at the repository root and fill in the
first two values:

```bash
cp .env.example .env
```

```text
NEO4J_PASSWORD=choose-one
GOOGLE_API_KEY=your-key
```

Those two are all you need. The rest have defaults, listed commented out in
the file; uncomment any of them to override:

| Variable | Default | What it is |
| --- | --- | --- |
| `NEO4J_PASSWORD` | none | **Required.** The database password, for the container and the app |
| `GOOGLE_API_KEY` | none | **Required** for chat and `embed`. A blank value counts as unset |
| `RULES_LAWYER_EMBEDDINGS` | `data/output/srd_embeddings.idx` | An embeddings file to use instead of generating one |
| `NEO4J_URI` | `bolt://localhost:7687` | |
| `NEO4J_USER` / `NEO4J_DATABASE` | `neo4j` / `neo4j` | |
| `CHAT_MODEL` | `gemini-3.8-flash` | The Gemini model that answers |
| `CHAT_TIMEOUT_SECONDS` | `60` | How long the model may stay silent before a turn fails |
| `EMBED_MODEL` | `gemini-embedding-001` | |
| `EMBED_DIMENSIONS` | `1536` | Changing it means regenerating the embeddings |

Parsing needs neither a database nor a key, and the server starts without a
key; only asking a question does.

Build the graph and start the API, from `backend/`:

```bash
cd backend
uv sync
uv run rules-lawyer parse       # the PDF into data/output/, about 30 seconds
uv run rules-lawyer embed       # embeddings, about 2 minutes (see below)
(cd .. && docker compose up -d neo4j)   # Neo4j Browser on :7474
uv run rules-lawyer load        # load the graph and verify it
uv run uvicorn rules_lawyer.api:app --reload
```

Then the app, from `frontend/`:

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Ask it a rules question and click a citation.

**Embeddings without spending API calls.** If someone has given you an
`srd_embeddings.idx`, skip `embed` and point at it instead:

```text
RULES_LAWYER_EMBEDDINGS=/path/to/srd_embeddings.idx
```

Re-running `embed` after a re-parse only embeds sections whose text changed.

## Project structure

```text
data/
  source/          the SRD PDF
  output/          generated: srd_hierarchy.{json,md,anchors.json}, srd_embeddings.idx
  chat/            saved conversations (SQLite)

backend/src/rules_lawyer/
  cli.py           rules-lawyer parse | embed | load
  api.py           the FastAPI app
  srd/             PDF to a validated JSON document of entities and edges
  graph/           that document and its embeddings into Neo4j
  chat/            the agent, its tools, retrieval and conversation storage

frontend/          React + Vite chat UI, proxying /api to :8000
e2e/               Playwright tests over the whole stack
```

[`backend/`](backend/README.md), [`frontend/`](frontend/README.md) and
[`e2e/`](e2e/README.md) each have a README covering their layout and commands,
tests included.

## Licence

The code is [MIT](LICENSE.md).

The SRD 5.2.1 is published by Wizards of the Coast under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Anything derived
from it, including the generated JSON, carries that licence and its
attribution requirement. [NOTICE.md](NOTICE.md) carries the attribution
statement the SRD requires, and names what it applies to.

This work includes material from the System Reference Document 5.2.1
("SRD 5.2.1") by Wizards of the Coast LLC, available at
<https://www.dndbeyond.com/srd>. The SRD 5.2.1 is licensed under the Creative
Commons Attribution 4.0 International License, available at
<https://creativecommons.org/licenses/by/4.0/legalcode>.
