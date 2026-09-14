# dnd-graph-rag

A personal project for trying out **knowledge-graph RAG**: retrieval that
walks a graph of typed entities and the relationships between them, rather
than only ranking chunks of text.

Dungeons & Dragons is the test domain, because it is a genuinely good one and
a fun one. The rules are intricate and deeply cross-referenced: a spell
imposes a condition, the condition changes how an attack resolves, a creature
is immune to it, a class feature granted the spell in the first place.
Questions like *"which creatures can Frighten, and with which ability?"* are
exactly the shape a graph answers well and a pile of embeddings answers
badly. The source is the D&D 5e SRD 5.2.1, which is 364 pages, freely
licensed, and shipped as a two-column PDF.

---

## What it does

Three stages, each meeting the next at one artifact on disk.

**1. The PDF becomes a document.** `srd-parse` reads the 364-page PDF and
writes `srd_hierarchy.json`: a tree of 2368 typed sections, plus flat
collections of creatures, spells, equipment, classes and glossary terms, and
5132 typed edges between them. It works at the line level and orders by text
baseline, because the book is two-column and PyMuPDF's own reading order
detaches a stat block's defence line from its stat block.

It **validates itself against the book** rather than hoping. 330/330 stat
blocks reconcile with the SRD's own Index of Stat Blocks, 697 damage averages
match their own dice, 413 attack bonuses match an ability modifier plus the
proficiency bonus, and 338 spells cross-check against the class spell lists.
The run fails loudly instead of quietly producing a wrong graph.

**2. The document becomes a graph.** `srd-graph-load` maps it into Neo4j,
4260 nodes and 11319 relationships, then verifies the result against the
artifact's own counts with 67 checks. The section tree is the spine: a spell
*is* its section with an extra `:Spell` label, so anything a traversal finds
still carries the character offsets that resolve it back to the book.

Every section with prose also carries a 1536-dimension embedding under a
vector index. That is the document half of a hybrid retriever; the chat does
not query it yet.

**3. The graph answers questions.** A LangGraph tool-calling agent on Gemini,
behind a React chat UI. Every rules claim in an answer is cited by section
id, and clicking a citation opens a side panel showing **the actual page of
the PDF it was printed on**, with the cited lines boxed on the page. The
offsets survive the whole way from the PDF to the answer and back. A second
tab draws that section's neighbourhood in the graph, walkable a node at a
time.

When the Gemini free tier runs out, the turn says so and offers a button to
answer the same question from the graph alone: same tools, same citations,
same page facsimile, with the passages left unsummarised and labelled as
such.

[GRAPH.md](GRAPH.md) documents every node label and relationship type.

---

## Project structure

A monorepo. `data/`, `docker-compose.yml` and `.env` are shared at the root;
every `uv` command runs from `backend/`.

```text
data/
  source/          the SRD PDF: checked in, never written to
  output/          generated: srd_hierarchy.{json,md,anchors.json},
                   srd_embeddings.idx
  chat/            conversation state (SQLite), not reproducible

backend/           the Python service
  src/dnd_graph_rag/
    config.py      settings: paths, Neo4j, chat, embeddings
    api.py         FastAPI: assembles each package's router
    srd/           stage 1: PDF to artifact
    graph/         stage 2: artifact to Neo4j
    chat/          stage 3: graph to answers
  tests/           one file per module, mirroring the package

frontend/          React + Vite chat UI; talks to :8000 through /api
e2e/               Playwright over the whole stack, on ports of its own
```

Nothing in `srd/` knows a database exists, nothing in `graph/` opens a PDF,
and nothing in `chat/` writes to either.

---

## Requirements

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/), for the backend
- **Node 22+**, for the frontend
- **Docker**, for the Neo4j container
- **A Gemini API key**, for the chat and to generate the embeddings once

The key is free-tier friendly. If you would rather not use one for the
embeddings, they are generated once and can be shared as a 13 MB file. See
step 2 of the quickstart.

### Environment variables

These live in a `.env` at the repository root, which is also what
`docker-compose.yml` reads. Only the first two matter to get started.

| Variable | Default | What it is |
| --- | --- | --- |
| `NEO4J_PASSWORD` | none | **Required.** Sets the container's password, and connects to it |
| `GOOGLE_API_KEY` | none | **Required by the chat**, and by `srd-embed`. A blank value counts as unset |
| `DND_GRAPH_RAG_EMBEDDINGS` | `data/output/srd_embeddings.idx` | Where the embeddings file lives. Point this at one you were given |
| `NEO4J_URI` | `bolt://localhost:7687` | |
| `NEO4J_USER` / `NEO4J_DATABASE` | `neo4j` / `neo4j` | |
| `CHAT_MODEL` | `gemini-3.8-flash` | The free tier's daily quota is per model, so switching it switches bucket |
| `CHAT_TIMEOUT_SECONDS` | `60` | How long the model may say *nothing* before the turn fails |
| `EMBED_MODEL` | `gemini-embedding-001` | |
| `EMBED_DIMENSIONS` | `1536` | Changing it means rebuilding the file and dropping the vector index |

A turn needs the model: there is no answering without it. Without a key
`POST /chat` is a 503 naming `.env`, and a rejected key or a spent quota ends
the turn with the error that says so — nothing answers in its place.

Each settings group is resolved lazily and only where it is needed, so
`srd-parse` runs with no database and no key, and the server starts without
one too.

---

## Quickstart

### Backend

Create a `.env` at the repository root:

```text
NEO4J_PASSWORD=choose-one
GOOGLE_API_KEY=…
```

Then, from `backend/`:

```bash
cd backend
uv sync
```

**1. Parse the PDF**, about 30 seconds.

```bash
uv run srd-parse
```

Reads `data/source/SRD_CC_v5.2.1.pdf` and writes `data/output/`. That output
is gitignored and reproducible; the PDF is never written to.

**2. Get the embeddings.** The graph load requires them, and there are two
ways to have them, and you only need one.

```bash
uv run srd-embed        # with a key: ~2 minutes, writes a 13 MB .idx
```

Or, if you already have the `srd_embeddings.idx` file, skip the API entirely:

```bash
echo 'DND_GRAPH_RAG_EMBEDDINGS=/path/to/srd_embeddings.idx' >> ../.env
```

Either way nothing after this point calls Google for embeddings, and running
`srd-embed` again makes no API calls at all: the file records a digest of
each section's text, so only sections that actually changed are re-embedded.

**3. Load the graph**, a few seconds.

```bash
(cd .. && docker compose up -d neo4j)    # browser on :7474, bolt on :7687
uv run srd-graph-load
```

That applies the schema, empties the graph, reloads it, and runs 67 checks
against the artifact's own counts. `--no-reset` merges instead of emptying;
`--skip-verify` skips the checks.

**4. Start the API.**

```bash
uv run uvicorn dnd_graph_rag.api:app --reload   # http://127.0.0.1:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev                              # http://localhost:5173
```

Vite proxies `/api` to the backend on `:8000`, so the browser stays on one
origin and the SSE stream shares it. That is the whole app: ask it a rules
question and click a citation.

### Tests

```bash
cd backend  && uv run pytest             # unit tests need nothing; the rest skip
cd frontend && npm test                  # vitest
cd e2e      && npm install && npm run install-browsers && npm test
```

The end-to-end run starts the API, the app and a Neo4j container of its own,
loads the graph from the artifact, and drives the real flows in a browser. It
runs with `CHAT_STUB=1`, a scripted model in place of Gemini, so it needs no
API key and no quota.

---

## Poking at the graph

The point of the whole exercise: questions that are a traversal rather than
a search. Neo4j Browser is on <http://localhost:7474>.

```cypher
// Which creatures can Frighten, and with which ability?
MATCH (c:Creature)-[:HAS_ABILITY]->(a:CreatureAbility)
      -[:IMPOSES_CONDITION]->(:Condition {name: 'Frightened'})
RETURN c.name, a.name ORDER BY c.name;

// Creatures that shrug off what Hold Person does
MATCH (:Spell {name: 'Hold Person'})-[:IMPOSES_CONDITION]->(cond)
MATCH (c:Creature)-[:IMMUNE_TO_CONDITION]->(cond)
RETURN cond.name, collect(c.name);
```

Both pipelines are importable too, if you would rather drive them from
Python:

```python
from dnd_graph_rag.srd import build, load
from dnd_graph_rag.graph import build_graph

document = build()        # parse and write
report = build_graph()    # report["validation"]["ok"] is True on a clean load
```

---

## Licence

The code is [MIT](LICENSE.md).

The SRD 5.2.1 is published by Wizards of the Coast under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Anything derived
from it, including the generated JSON, carries that licence and its
attribution requirement. [NOTICE.md](NOTICE.md) carries the attribution
statement the SRD requires, and names what it applies to.

This work includes material from the System Reference Document 5.2.1
(“SRD 5.2.1”) by Wizards of the Coast LLC, available at
<https://www.dndbeyond.com/srd>. The SRD 5.2.1 is licensed under the Creative
Commons Attribution 4.0 International License, available at
<https://creativecommons.org/licenses/by/4.0/legalcode>.
