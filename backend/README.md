# Backend

The Python service behind Rules Lawyer. It does three jobs, in three
packages, each handing the next one file:

1. **`srd/`** reads the SRD PDF and writes `data/output/srd_hierarchy.json`:
   the book as a tree of typed sections (spells, creatures, rules, ...) plus
   the cross-references between them.
2. **`graph/`** loads that JSON, with one embedding per section, into Neo4j.
3. **`chat/`** answers questions with an agent that searches and walks the
   graph, and cites the sections it used.

`api.py` puts all three behind one FastAPI app, which the frontend talks to.
See the [project README](../README.md) for setup and
[GRAPH.md](../GRAPH.md) for every node label and relationship type.

Run everything from this directory. `data/` and `.env` are read from the
repository root wherever you run from.

## Commands

```bash
uv sync                                         # install

uv run rules-lawyer parse                       # PDF -> data/output/srd_hierarchy.{json,md,anchors.json}
uv run rules-lawyer embed                       # JSON -> srd_embeddings.idx (needs GOOGLE_API_KEY)
uv run rules-lawyer load                        # JSON + embeddings -> Neo4j, then verify
uv run uvicorn rules_lawyer.api:app --reload --reload-include '*.md'
uv run pytest                                   # the tests; see Tests below
```

Each command has `--help`. The useful options:

| Command | Option | Does |
| --- | --- | --- |
| `parse` | `--pdf`, `--out` | read another PDF, write somewhere else |
| `embed` | `--refresh` | re-embed every section, ignoring the existing file |
| `load` | `--no-reset` | merge into the graph instead of emptying it first |
| `load` | `--skip-verify` | skip the post-load checks |
| `load` | `--embeddings PATH` | use a given `srd_embeddings.idx` |

`parse` exits non-zero if the book disagrees with itself in a way not on its
list of known quirks; `load` exits non-zero if verification fails.

Neo4j runs in Docker: `docker compose up -d neo4j` from the repository root.
The browser at <http://localhost:7474> is handy for trying Cypher by hand.

`--reload-include '*.md'` restarts the server when a prompt file changes.

## Layout

```text
src/rules_lawyer/
  cli.py              the rules-lawyer command
  api.py              the FastAPI app: every package's router, plus the
                      SQLite stores for conversations
  config.py           settings from .env (paths, NEO4J_*, CHAT_*, EMBED_*)

  srd/                PDF -> JSON
    reading/          PDF pages -> lines -> styled text -> blocks
                      (paragraphs, lists, tables, stat blocks)
    sections.py       blocks -> the section tree
    entity_types.py   what each section is (spell, creature, rule, ...)
    entities/         typed records: creatures, spells, equipment, classes,
                      glossary terms, and the cross-reference edges
    output/           JSON in and out, markdown rendering, page anchors
    verify.py         the book checked against itself
    artifact.py       build, write and load the whole document
    routes.py         /health, /parse, /pdf

  graph/              JSON -> Neo4j
    mapping.py        the document as node and edge batches (pure, no I/O)
    embeddings.py     section texts, the .idx file, what needs re-embedding
    schema.py         constraints, indexes, full-text and vector index
    loader.py         batched writes
    verify.py         checks the loaded graph against the document
    pipeline.py       ties the above together
    routes.py         /graph/health, /graph/load

  chat/               questions -> cited answers
    agent.py          the LangGraph agent on Gemini
    tools.py          the four tools the agent can call
    retrieval.py      full-text, vector and fused search
    cypher.py         safe, read-only Cypher for the agent
    neighbourhood.py  a bounded walk around one node
    service.py        one turn as a stream of events; thread storage
    source.py         a citation -> markdown slice and page boxes
    titles.py         short conversation titles
    stub.py           a scripted model for tests (CHAT_STUB=1)
    prompts/          the system prompt and friends, sent verbatim
    routes.py         /chat, /chat/threads/*, /source, /neighbourhood

tests/                mirrors src/: tests/graph/test_mapping.py tests
                      graph/mapping.py
```

## Features

**Stack.** Python 3.12, managed with uv. FastAPI and uvicorn for HTTP,
pydantic for the document's types and pydantic-settings for configuration,
PyMuPDF to read the PDF, the official `neo4j` driver, and LangChain with
LangGraph for the agent. No numpy, FAISS or vector database beyond Neo4j.

**PDF extraction (`srd/`).** PyMuPDF gives text spans with their fonts and
positions; everything above that is ours. Lines are ordered by baseline
within measured columns, typography decides headings, tables are rebuilt from
text x positions, and stat blocks are parsed as cards. The output is typed
blocks in a section tree, with entity records (creatures, spells, items,
classes, glossary terms) and cross-reference edges read from the book's
markup: italics for spells and items, bold for creatures. `verify.py` then
holds the book to itself, for example every stat block against the book's own
index and every damage average against its dice.

**Database: Neo4j 5.26 Community.** The section tree is the spine: a spell is
its `:Section` node with an extra `:Spell` label, so anything a query finds
still carries the character offsets that locate it in the book. Derived nodes
(creature abilities, class levels, damage types, weapons) hang off it.
Uniqueness constraints double as the indexes loads `MERGE` on. Writes are
batched `UNWIND`s, and a load empties the graph first by default, since the
JSON is the whole truth. [GRAPH.md](../GRAPH.md) lists every label and
relationship.

**Embeddings.** Gemini `gemini-embedding-001`, one vector per section with
prose, truncated to 1536 dimensions and normalised. They live in
`srd_embeddings.idx`, a small binary format of our own (a JSON header, then
raw float32), whose header records a digest of each section's text, so a
re-parse re-embeds only what changed. On load they go into a Neo4j vector
index (`srd_vector`, cosine).

**Search: hybrid.** Two arms, because they fail differently: Neo4j's Lucene
full-text index (`srd_text`, BM25) misses questions sharing no words with the
book, and the vector index blurs exact terms (Fire and Cold damage sit close
together). Each returns its top candidates, and reciprocal rank fusion
(k = 60) merges them by rank, not score, since the two scores are not
comparable. Questions are embedded live; without an API key search falls
back to full-text only.

**Agent.** A LangGraph tool-calling agent (`langchain.agents.create_agent`)
on Gemini (`CHAT_MODEL`, pinned), with a system prompt that includes the
graph's schema, derived from the loaded data (and left out while the graph
is unreachable). It has four tools:

| Tool | What it does |
| --- | --- |
| `search_srd` | hybrid search, optionally filtered by entity type |
| `get_srd_section` | one section by its dotted id, with parent and children |
| `explore_srd_graph` | a bounded walk around a section, as prose the model can cite |
| `query_srd_graph` | read-only Cypher, for exhaustive "list every X" questions |

Agent-written Cypher runs in a read-access transaction, so Neo4j itself
refuses writes; procedures are allow-listed, and rows, cell sizes and run
time are capped. The tool docstrings and the files in `chat/prompts/` are
sent to the model as written, so editing them changes its behaviour.

**Citations.** The model cites sections as `[11.2.114]`. Ids are resolved
against the graph after the answer is written, and invented ones are dropped.
`/source/{id}` turns an id into the markdown it covers and its rectangles on
the PDF page (from `srd_hierarchy.anchors.json`), which the frontend draws
over the page.

**Streaming.** `service.stream_turn` turns one LangGraph run into typed
events (`start`, `token`, `tool_start`, `tool_end`, `usage`, `citations`,
`error`, `done`), sent as Server-Sent Events. A turn fails after
`CHAT_TIMEOUT_SECONDS` of silence, and every failure arrives as an `error`
event; there is no fallback answer.

**Memory and storage.** Conversation history is LangGraph's: an
`AsyncSqliteSaver` checkpointer in `data/chat/chat.sqlite`, keyed by a
thread id the browser holds, so a thread is its checkpoints. Pins and titles
are in a separate `AsyncSqliteStore` (`chat-store.sqlite`). Retry rewinds to
the checkpoint before the last question and branches from it. Each tool
result is checkpointed too, and fetched on demand to show a lookup's detail.
Titles are written by the model beside the first turn.

**Configuration.** `config.py` reads `.env` and the environment; each group
(Neo4j, chat, embeddings) is built only when first used, so parsing needs no
database or key.

## API

Interactive docs are at <http://127.0.0.1:8000/docs> while the server runs.
The frontend reaches all of these under `/api`.

| Endpoint | Does |
| --- | --- |
| `GET /health` | paths, and whether the PDF and the JSON exist |
| `POST /parse` | run the parse; returns counts and validation |
| `GET /pdf` | the source PDF |
| `GET /graph/health` | whether Neo4j is reachable, and its counts |
| `POST /graph/load` | run the load |
| `POST /chat` | ask a question; answers as a Server-Sent Event stream |
| `GET /chat/threads` | every conversation, pinned first |
| `GET /chat/threads/{id}` | one conversation's turns |
| `GET /chat/threads/{id}/lookups/{call_id}` | one tool call's full result |
| `POST /chat/threads/{id}/retry` | ask the last question again |
| `PUT /chat/threads/{id}/pin` | pin or unpin |
| `DELETE /chat/threads/{id}` | delete |
| `GET /source/{section_id}` | a cited section: its text, page boxes, ancestors and children |
| `GET /neighbourhood` | the graph around a section or node, for the graph view |

`POST /chat` answers 503 without a `GOOGLE_API_KEY`; any other failure
arrives as an `error` event in the stream.

## Tests

```bash
uv run pytest                    # everything
uv run pytest -m "not neo4j"     # only the tests that need no database: seconds, no Docker
uv run pytest -m neo4j           # only the tests that need the database
uv run pytest tests/srd          # one package
uv run pytest tests/graph/test_mapping.py -k fold   # one file, tests matching a name
```

Unit tests need nothing. Tests that need the
generated JSON, the embeddings or an API key skip cleanly without them.

**Tests that need Neo4j get their own.** The first one to ask starts a
throwaway `neo4j:5.26-community` container with
[Testcontainers](https://testcontainers.com/), loads the parsed SRD and its
embeddings into it once, and removes it when the run ends. Your development
database is never touched: for the whole run every `NEO4J_*` setting points
at the container, or at nothing. Without Docker those tests skip.

These tests carry `@pytest.mark.neo4j`, so `-m "not neo4j"` runs the other
four fifths in seconds. Writing one? Ask for the `graph` fixture (a session
on the loaded container) and add the mark, on the class if every test in it
needs the database. Collection fails if the mark and the fixture disagree.

Conventions: one test file per module, each test a method on a class named
for the function under test, written as Given / When / Then.
