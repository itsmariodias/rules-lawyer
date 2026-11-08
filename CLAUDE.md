# dnd-graph-rag

Knowledge-graph RAG over the D&D 5e SRD (`SRD_CC_v5.2.1.pdf`, 364 pages).

Three stages, each meeting the next at one artifact:

1. **`srd/`**: PDF to `srd_hierarchy.json`, a self-validating document of typed
   entities and the edges between them.
2. **`graph/`**: that artifact (plus embeddings) into Neo4j.
3. **`chat/`**: questions answered from the graph, citing the book.

Nothing in `srd/` knows a database exists, nothing in `graph/` opens a PDF,
and nothing in `chat/` writes to either.

## Layout

A monorepo. `backend/` is the Python service, `frontend/` the React UI, and
`data/`, `docker-compose.yml` and `.env` are shared at the root. Every `uv`
command runs from `backend/`; `config.py` resolves `data/` and `.env` from the
repository root regardless of the working directory.

```text
data/
  source/            the SRD PDF; checked in, never written
  output/            srd_hierarchy.{json,md,anchors.json}: reproducible
                     srd_embeddings.idx: reproducible only with an API key,
                     so also shared as a file (DND_GRAPH_RAG_EMBEDDINGS)
  chat/              chat.sqlite (checkpoints), chat-store.sqlite (pins,
                     titles): not reproducible

backend/src/dnd_graph_rag/
  config.py          pydantic-settings: DND_GRAPH_RAG_*, NEO4J_*, CHAT_*, EMBED_*
  api.py             FastAPI app; assembles each package's router
  srd/               stage 1
    layout.py        PDF -> ordered, styled lines -> markdown + page anchors
    statblocks.py    lines -> creature records
    mechanics.py     attacks, saves, damage, conditions imposed
    equipment.py     weapons, armour, gear
    character.py     classes, species, backgrounds, feats, poisons, damage types
    references.py    glossary terms and cross-reference edges
    pipeline.py      tree, entity typing, validation, srd-parse CLI
    routes.py        /health, /parse, /pdf
  graph/             stage 2
    model.py         NodeBatch / EdgeBatch: the mapper/loader seam
    mapping.py       document -> batches; pure, no driver or I/O
    embeddings.py    section texts, the .idx file format, generation policy
    schema.py        constraints, indexes, full-text and vector index, reset
    loader.py        batched UNWIND writes
    verify.py        post-load checks against the artifact
    pipeline.py      orchestration
    cli.py           srd-graph-load, srd-embed
    routes.py        /graph/health, /graph/load
  chat/              stage 3
    retrieval.py     lexical, dense and fused search; one section by id;
                     CITATION, the citation pattern
    cypher.py        guard, read-only transaction, derived schema, rendering
    neighbourhood.py bounded walk around one node (graph view and tool)
    tools.py         the four agent tools
    agent.py         LangGraph agent on Gemini
    service.py       one turn -> typed event stream; thread storage; rewind
    source.py        a citation -> markdown slice and page rectangles
    titles.py        conversation titles
    stub.py          scripted model for the test suites (CHAT_STUB)
    prompts/         system.md, graph-orientation.md, title.md
    routes.py        /chat, /chat/threads/*, /source/{id}, /neighbourhood

frontend/src/
  api.ts             client; ChatEvent mirrors service.py's events
  useChat.ts         conversation state for the open thread
  useStored.ts       localStorage-backed state and theme
  useGraphStatus.ts  graph availability, polled until connected
  App.tsx            shell: thread list, conversation, side panel
  components/        Markdown, ToolTrace, Timing, Usage, SidePanel, PdfPage,
                     GraphView, graph-layout (pure layout maths), Resizer
  index.css          all styles; colour tokens at the top

e2e/                 Playwright over the whole stack (see Testing)
GRAPH.md             reference for every label and relationship type
```

## Conventions

- **Tests:** one file per module, mirroring the package
  (`tests/graph/test_mapping.py` for `graph/mapping.py`; `api.test.ts` beside
  `api.ts`). Each test is a method on a class (or a `describe`) named for the
  function under test, written Given / When / Then with those comments.
  Unit tests need nothing; tests needing the artifact, vectors, an API key or
  Neo4j skip cleanly without them.
- **Docstrings:** Google style. Public functions document `Args`, `Returns`,
  `Raises` (and `Yields`) where they apply; private helpers get one line.
- **Comments** only for what the code cannot say: a library quirk, a bug
  being prevented, an SRD fact, a measured number. Design rationale lives here.
- **No em-dashes** in code, comments or docs.
- **Tool docstrings in `chat/tools.py` are prompt text.** LangChain parses
  them into the tool descriptions and `Args:` into the parameter schema, so
  edits change model behaviour.
- **Prompt files** in `chat/prompts/` are sent verbatim: one paragraph per
  line, since a line break in the file reaches the model. Only the trailing
  newline is stripped. They are read at import, so a misspelt name fails at
  startup.
- **Commits:** conventional (`type(scope): subject`), on `main`.

## Configuration

`config.py` reads `.env` and the environment.

- `Settings` holds the paths. `Settings.neo4j`, `.chat` and `.embedding` are
  `cached_property`s built on first access, so `srd-parse` needs no
  `NEO4J_PASSWORD` and neither pipeline needs `GOOGLE_API_KEY`.
- Paths a keyless process must know (`checkpoint_name`, `store_name`,
  `embeddings_path`) live on `Settings`, because building `ChatSettings` or
  `EmbeddingSettings` is where the key matters.
- Paths are resolved inside `build()`/`load()`, not as import-time defaults,
  so environment overrides take effect.
- `GOOGLE_API_KEY` is shared by chat and embeddings (the `ApiKey` type). A
  **blank** value counts as no key: an unset variable does not override an
  `.env` that sets one, so `GOOGLE_API_KEY=` is how to force the keyless path.
- Embedding settings: `EMBED_MODEL`, `EMBED_DIMENSIONS`, `EMBED_TASK_TYPE`,
  `EMBED_BATCH`, `EMBED_MAX_CHARS`, `EMBED_WRITE_BATCH`.

## Running it

```bash
docker compose up -d neo4j                     # NEO4J_PASSWORD from .env

cd backend
uv run srd-parse                               # data/output/srd_hierarchy.{json,md}
uv run srd-parse --pdf other.pdf --out /tmp/x.json
uv run srd-embed                               # srd_embeddings.idx; needs a key
uv run srd-graph-load                          # artifact + vectors -> graph, verify
uv run srd-graph-load --no-reset --skip-verify
uv run srd-graph-load --embeddings ~/Downloads/srd_embeddings.idx
uv run pytest
uv run uvicorn dnd_graph_rag.api:app --reload --reload-include '*.md'

cd ../frontend && npm install && npm run dev   # http://localhost:5173
npm test                                       # vitest
npm run coverage

cd ../e2e && npm install && npm run install-browsers && npm test
```

`--reload-include '*.md'` makes editing a prompt file restart the server.

The pipeline is importable: `from dnd_graph_rag.srd import build, load`.
Progress goes through an injected `report` callable (the CLI passes `print`).
No package's `__init__` imports its `routes.py`, so importing a pipeline pulls
in no web framework.

## API

```text
GET  /health                          paths, and whether PDF and output exist
POST /parse                           {"pdf", "out"}; returns meta, validation,
                                      paths written (never the document)
GET  /pdf                             the source PDF (range requests, cached)
GET  /graph/health                    reachability and counts; 503 if down
POST /graph/load                      {"input", "reset", "skip_verify",
                                      "embeddings", "refresh_embeddings"};
                                      404 no artifact, 409 no vectors and no key
POST /chat                            {"message", "thread_id"} -> SSE; 503 no key
GET  /chat/threads                    pinned first, then newest
GET  /chat/threads/{id}               one conversation's turns
GET  /chat/threads/{id}/lookups/{call_id}  one tool call's stored result
POST /chat/threads/{id}/retry         re-ask the last question -> SSE; 404 empty
PUT  /chat/threads/{id}/pin           {"pinned"}; 404 if no such thread
DEL  /chat/threads/{id}               delete; 404 if no such thread
GET  /source/{id}?context=400         markdown slice, highlight offsets, boxes,
                                      ancestors, parent, children
GET  /neighbourhood?section=|node=    &depth &fan &limit
```

- The Neo4j driver is synchronous, so graph endpoints use `run_in_threadpool`.
- The API holds no state. `lifespan` opens one `AsyncSqliteSaver`
  (checkpoints) and one `AsyncSqliteStore` (pins and titles); routes reach
  them through `request.app.state`.
- Each package owns its `routes.py`; `/pdf` lives with stage 1 because it
  serves stage 1's input.

## Stage 1: the artifact

`data/output/srd_hierarchy.json` holds `meta`, `sections` (a tree), flat
collections and `validation`. `srd_hierarchy.md` is written beside it, and
every node's `char_start`/`char_end` slices it. `srd_hierarchy.anchors.json`
maps those character ranges to page rectangles.

| Collection | Count | Notes |
| --- | --- | --- |
| sections | 2368 | tree; every node has an `entity_type` |
| creatures | 336 | stat blocks; mechanics on 706 entries |
| equipment | 146 | 38 weapons, 13 armour, 81 gear, 14 poisons |
| classes | 12 | core traits, 20-level progression, features, subclasses |
| species / backgrounds / feats | 9 / 4 / 17 | |
| glossary | 172 | 15 conditions, 13 damage types, 12 actions, 4 poison types, ... |
| references | 5266 | typed edges between all of the above |

| `entity_type` | Count |
| --- | --- |
| `class_feature` / `rule` | 446 / 382 |
| `spell` / `magic_item` (with a `spell` / `item` block) | 339 / 258 |
| `creature` (its stat block) / `creature_group` (`members`) | 336 / 179 |
| `equipment` (81 are the gear items themselves) | 194 |
| `glossary_term` (`term`, `term_type`) | 155 |
| `origin` / `feat` / `front_matter` | 32 / 24 / 3 |
| `environmental_effect` / `trap` / `contagion` | 9 / 8 / 3 |

### Extraction decisions

- **Line level, not `pymupdf4llm`.** PyMuPDF's block order sometimes sorts a
  bottom-of-column fragment after the facing column, which detached a
  creature's `AC / Initiative / HP / Speed` line from its stat block. Lines
  are ordered by **baseline**, because bbox tops are inflated by font metrics.
- **Columns are measured,** from empty vertical strips, then snapped to the
  book-wide grid (342 of 364 pages are two columns; the contents run three
  and four). A table spanning the gutter hides the strip, so a page whose
  frames are all grid columns adopts the full grid.
- **Tables:** PyMuPDF's finder gives the region only; cells come from text x
  positions, since most rows have no ruling lines. `_absorb_edge_rows`
  reclaims unshaded rows just outside the detected rectangle (583 fragments
  across 160 tables).
- **Typography carries structure.** `GillSans-SemiBold` at 26/18/14/12/10.5pt
  is H1 to H5. Stat block titles are 14.8pt and are emitted at the deepest
  level so a creature printed inside a spell nests under it. Stat block
  section headers ("Traits", "Actions") are plain GillSans 12. Small-caps
  sidebar headings extract as mixed case ("rEstinG") and are recased.
- **A stat block is parsed as a card,** keyed off its title, not assembled
  from whatever prose fell under a heading.
- **Page anchors** are recorded per emitted part (reflowing destroys
  per-character correspondence; sections start and end on part boundaries).
  A line's box comes from baseline and size (`baseline - 0.80*size` to
  `baseline + 0.24*size`): PyMuPDF reports 95 of 107 lines on a typical page
  as 56pt tall. Horizontal extent is reliable. Geometry stays on disk, not in
  the graph.
- **Cross-reference edges come from markup.** Spells and magic items are
  italic, creatures bold; a span becomes an edge only if it resolves to an
  extracted entity (italics also mark emphasis and book titles). Conditions,
  actions, damage types and areas match on fixed phrasing (`Prone
  condition`, `a 20-foot Cone`) so `Cover`, `Attack` and `Force` never fire as
  bare nouns. Name lists ("the Deafened and Frightened conditions") count
  every name, *or* lists included, since they are mentions.
- **`imposes_condition` vs `references_condition`.** Only
  `mechanics.conditions_imposed` decides "imposes": "has the X condition"
  (X may be an *and* list), skipped when a negating word appears in the same
  clause (after the last `,` `;` or `.`). *Or* lists are not imposed: "the
  Grappled, Incapacitated, or Restrained condition" is usually target
  eligibility. Reading only single names left the Tarrasque's Thunderous
  Bellow imposing nothing.
- **`spell` and `magic_item` come only from the subtitle** the book prints
  under the heading, never from position: a table printed as a subsection
  of a spell ("Teleportation Outcome") is not a spell. **`creature_group`
  is only assigned in the monster chapters;** elsewhere a printed stat block
  (a summoned creature, a figurine) is a `creature` and the spell or item
  around it keeps its type. Both rules once put Find Steed and five others
  in the wrong type and miscounted spells as 343.
- **Closed sets get a type.** `ENTRY_SET_ENTITY_TYPES` types traps,
  environmental effects and contagions, which were indistinguishable `rule`
  sections. Entries are the heading's children, or its following siblings
  when the book prints them at the same level ("Example Contagions").
- **Gear and poisons record `section_id`** so stage 2 folds them into their
  section. Without it there were 95 duplicate nodes and 60 duplicate edges.

## Stage 2: the graph

`srd-graph-load` writes **4260 nodes and 11453 relationships**, then runs
**68 verification checks**. Loads MERGE on stable keys, but a full reset is
the default: the artifact is the whole truth, and merging alone would keep
nodes a re-parse has dropped.

| Label | Key | Count |
| --- | --- | --- |
| `:Section` | `id` | 2368 |
| + `:Spell` / `:MagicItem` / `:Creature` / `:Rule` / `:ClassFeature` / ... | `id` | 339 / 258 / 336 / 382 / 446 / ... |
| + `:Trap` / `:EnvironmentalEffect` / `:Contagion` | `id` | 8 / 9 / 3 |
| `:CreatureAbility` | `key` (`Goblin\|actions/Bite`) | 1314 |
| `:GlossaryTerm` + `:Condition` / `:DamageType` / `:PoisonType` / ... | `name` | 172 |
| `:Equipment` + `:Weapon` / `:Armor` | `name` | 51 table rows |
| + `:Gear` / `:Poison`, folded into their sections | `id` | 81 / 14 |
| `:Class` / `:Subclass` / `:ClassLevel` | `name` / `key` / `key` | 12 / 12 / 240 |
| `:Species` / `:Background` / `:Feat` / `:Trait` | `name` / ... / `key` | 9 / 4 / 17 / 61 |

Relationships: the artifact's reference relations uppercased
(`IMPOSES_CONDITION`, `REFERENCES_SPELL`, ...); structure (`HAS_SUBSECTION`,
`HAS_ABILITY`, `HAS_FEATURE`, `HAS_SUBCLASS`, `AT_LEVEL`, `GRANTS_FEATURE`,
`HAS_TRAIT`, `DEFINED_IN`); and edges derived from list fields
(`IMMUNE_TO`, `RESISTANT_TO`, `VULNERABLE_TO`, `IMMUNE_TO_CONDITION`,
`ON_SPELL_LIST`, `CARRIES`, `HAS_POISON_TYPE`, `GRANTS_FEAT`). GRAPH.md
documents each one; `tests/test_docs.py` fails if it falls behind `mapping`.

### Graph decisions

- **The section tree is the spine; entity types are extra labels.** A spell
  *is* its section, so everything a traversal finds keeps
  `char_start`/`char_end` and resolves to the book. The dotted section id is
  the only globally unique stable identifier, so it is the key.
- **A stat block, gear item or poison folds into its section** (336 creatures
  on both sides, names unique; `add_creatures` raises if not). Weapons and
  armour are only table rows, so they stay `:Equipment` nodes. Glossary terms
  cannot fold: all 13 damage types share section `11.2.46.1`.
- **Abilities are nodes because references point at them.** A
  creature-sourced reference's `part` (`actions/Bite`) is the tail of the
  ability key, so 1582 edges land on the ability rather than the whole stat
  block.
- **Targets are matched, never merged.** An unresolved target is reported in
  `unresolved`, not created as an empty node. All 5266 currently resolve.
- **Poison types are nodes** because nothing refers to them; without
  `HAS_POISON_TYPE` the paragraph defining "Injury" is unreachable.
- **`mapping.py` is pure.** No driver; `loader.py` only batches and writes.
- **Nested values fail at map time.** Neo4j stores primitives and homogeneous
  arrays; `clean()` raises naming the field (Neo4j names only the value).
  Damage lists become parallel `damage_dice` / `damage_types` /
  `damage_averages`; `resources` becomes `resource_names` / `resource_values`.
- **Uniqueness constraints double as the MERGE indexes.**

### Embeddings

- One vector per section with prose (`EMBED_DIMENSIONS`, default 1536,
  truncated from 3072 and normalised by us, since the API only normalises at
  full width). The text is prefixed with its heading path
  (`Monsters > Goblin > Actions`), because dozens of sections are called
  "Actions".
- **Required.** A load with neither a complete `.idx` nor a key raises
  `MissingEmbeddings` before opening a session, leaving the previous graph
  standing. The message names both ways out.
- **`.idx` format:** magic `DNDEMB\0`, a uint32 header length, a JSON header
  (model, dimensions, task type, keys, per-section text digests), then raw
  little-endian float32. Standard library only (`array`), no numpy or FAISS.
- **The header makes it a cache.** Digests mean a re-parse re-embeds only the
  changed sections. A file made under another model, width or task type is
  discarded whole: two vector spaces in one index rank nonsense silently.
  Truncation (`EMBED_MAX_CHARS`) happens before the digest.
- Vectors are written in their own pass (`EMBEDDING_QUERY`), so `mapping`
  stays pure and `clean()` never walks 1536 floats per row.
- **`apply_schema` drops `srd_vector` if its width differs** from the vectors
  being written; `CREATE ... IF NOT EXISTS` would keep the old index, which
  indexes nothing of the new width.

### Verification (`verify.py`)

Expected values come from the document (`meta.counts`, collections), never
from the loader's tally. Checks: a count per exact label set and per
`entity_type`; collections; 336 creatures with stats; 16 roots and one parent
per section; all 5266 reference edges and zero unresolved; 1314 abilities,
each attached; abilities with damage; sections with prose each having a
vector of the right width; `srd_vector` online and of that width; no orphans
beyond two exemptions. Non-zero failures exit non-zero.

Exempt orphans, both facts about the book: the 3 front-matter roots, and 20
weapon and armour rows printed only in a table.

## Stage 3: the chat

A LangGraph tool-calling agent (`langchain.agents.create_agent`) on Gemini
(`CHAT_MODEL`, pinned) with four tools:

| Tool | Does |
| --- | --- |
| `search_srd` | hybrid search; `CHAT_SEARCH_LIMIT` candidates per arm, fused to `CHAT_TOP_K` |
| `get_srd_section` | one section by dotted id, with parent and children |
| `explore_srd_graph` | the bounded walk around a section, as prose |
| `query_srd_graph` | read-only Cypher |

`service.stream_turn` flattens LangGraph's stream into events: `start`,
`token`, `tool_start`, `tool_end`, `usage`, `citations`, `error`, `done`.
`routes.py` encodes them as SSE; tests iterate them directly.

### Retrieval

- **Two arms because they fail differently.** Lucene (`srd_text`, BM25)
  cannot match a question sharing no words with the book; the dense arm
  (`srd_vector`) cannot be trusted on exact terms (Fire and Cold damage are
  neighbours).
- **Fused by rank** (reciprocal rank fusion, k=60), not score: BM25 is
  unbounded, cosine is in [-1, 1]. `Passage.found_by` records which arms
  returned each passage.
- **Queries are embedded live** under `RETRIEVAL_QUERY` (documents use
  `RETRIEVAL_DOCUMENT`), cached on the text. Without a key `embed_query`
  returns `None` and search is lexical only. That is the only degradation;
  any other API failure is an error.
- A dense index always has a nearest neighbour, so search no longer says
  "nothing matched" unless both arms are empty. Judging relevance is the
  model's job, and the system prompt says so.
- Type filters are applied after the index (the index must rank), asking
  for 5x the limit.
- Parameters go to Neo4j as a dict: one is named `query`, which collides with
  `Session.run`'s first parameter.

### Agent-written Cypher

- Exists for exhaustive questions ("which creatures can make someone
  Frightened"): a search returns passages and a walk a sample, and the model
  verifies every row of either.
- **The write boundary is the transaction:** a `READ_ACCESS` session and an
  explicit transaction, so Neo4j refuses writes with `AccessMode`. A keyword
  denylist would also refuse `WHERE s.name = 'Create Undead'`.
- **The guard covers what read access allows:** procedures are allow-listed
  (`dbms.listConfig()` is a read that returns server config) and `LOAD CSV`
  is refused. String literals are blanked first, so names never trip it.
- **Bounds:** `CHAT_CYPHER_MAX_ROWS` (one extra row read to detect
  truncation) and `CHAT_CYPHER_TIMEOUT_SECONDS` (a cartesian product costs its
  time before sending a row). Cells are cut at 600 chars (at 200, 22% of
  ability descriptions were cut and the model fetched each section); whole
  rows are dropped past 12,000 chars.
- **Errors are results:** the model reads the message and retries. Only
  `AccessMode` is reworded (Neo4j's text is "Unexpected error has occurred").
- **The schema is in the system prompt, derived.** `shapes()` reads which
  labels each relationship joins from the data (0.14s, cached), because
  `db.schema.visualization` reports label combinations no node has on a
  multi-label graph. `graph-orientation.md` adds what introspection cannot
  say, chiefly which chains answer which question. Measured on the
  Frightened question (median of 5): schema alone 29 tool calls, with the
  idiom 12, with the 600-char cell cap 8.
- **If the graph is unreachable the prompt omits the schema** rather than
  failing the turn. `build_agent` recomputes the prompt each call and
  `compile_agent` caches on (checkpointer, prompt), so the schema is picked
  up once the graph is reachable.

### The graph walk (`explore_srd_graph`, `/neighbourhood`)

- Bounded by `depth` hops, `fan` neighbours per (node, type, direction), and
  `limit` nodes; what the caps cut is reported in `truncated`
  ("121 in the graph, 8 shown"). A hub such as Poison damage has 195 edges.
- Samples are the highest-degree neighbours, name as tie-break, so they are
  deterministic and informative (alphabetical sampling showed only leaves).
- The node budget is spent in discovery order; an edge whose far end did not
  fit is dropped. The tool raises the budget with `fan`, otherwise a wider
  fan starves the other groups.
- Every neighbour carries something to cite: a section cites itself; an
  ability cites the stat block printing it (`HAS_ABILITY`), a glossary term
  its `DEFINED_IN` section; anything printed nowhere says "do not cite".
  Without this the model searched for each node by name.
- A citation names a section, and the derived term other things point at is
  one hop further, so the docstring tells the model to walk depth 2 when
  depth 1 shows only structure.
- Nodes are addressed by `elementId` (stable for the life of a load), since
  derived nodes have no section id.

### Answers, failures and citations

- **The model is required, and a failure is the reply.** No fallback answer.
  A missing key is knowable before the stream starts, so `/chat` answers 503;
  everything else arrives as an `error` event. `_explain` names the common
  failures (no key, rejected key, spent quota) and truncates the rest.
- **A stall is not an error by itself,** so `_until_silent` fails a turn
  after `CHAT_TIMEOUT_SECONDS` of silence, reset by every token and tool
  result.
- **`CHAT_STUB` is a test seam, not a fallback:** `stub.py` calls the real
  `search_srd` and cites the first result. It lives in the package because
  e2e drives a real uvicorn process.
- **Citations come from the answer.** The prompt asks for `[11.2.114]` after
  each claim; `resolve_citations` resolves the ids in the finished text, in
  order of first appearance, dropping invented ones. The pattern is
  `retrieval.CITATION`; `Markdown.tsx` has a copy that `test_docs.py` holds
  against it.
- **The id is what the model writes; a number is what the reader sees.**
  `Markdown` numbers resolved citations `[1]`, `[2]` and the list below is the
  legend; the id is in the title. Unresolved ids stay as written, unlinked.
  Asking the model to number sources produced renumbering mid-answer.
- **Tool artifacts:** each tool returns `(content, artifact)`. The artifact
  (`status` of ok / empty / refused / failed, `summary`, `subject`) rides on
  the `ToolMessage`, is never shown to the model, and drives the trace.
  `empty` is a valid answer, not a failure.
- **Usage** is summed from `usage_metadata` over a turn's model calls, live
  (sent before `done`, after an `error` too) and when reopened. A turn
  without counts shows nothing. The stub reports a fixed 1230 per call.

### Threads

- History lives in the checkpointer, keyed by a thread id the browser holds.
  There is no thread table: deleting the checkpoints is deleting the thread.
- **Pins and titles live in a separate store,** because the checkpointer's
  tables are LangGraph's. Unpinning deletes the row. Deleting a thread
  deletes its pin and title. Store reads pass an explicit `limit`:
  `asearch` defaults to 10, which silently unpinned an eleventh thread.
- **Titles:** the opening turn asks the model for at most five words, in a
  task running beside the turn (the first token waits for nothing), stored
  before the stream ends. Any failure means no title, and the list falls
  back to the cut question. Whether a turn is the opening one is asked of the
  checkpointer, since a client may mint its own id.
- **Retry is a rewind, not a second question.** The checkpointer cannot drop
  one checkpoint, so `rewind` finds the newest checkpoint without the last
  question and the retry branches from it; later checkpoints stay on disk,
  unreachable. The question is read from the checkpoint, not resent. The
  graph checkpoints before the input, so the first turn also has a state to
  branch from. An empty thread is a 404 before the stream starts.
- **Reopened conversations keep their trace:** `turns_of` (pure) attaches
  tool calls to the answer that follows them; a failed turn's calls do not
  leak into the next. `name_missing_subjects` fills `subject` for threads
  stored before tools returned artifacts.
- **Tool results are fetched on demand** (`/lookups/{call_id}`): one turn of
  the Frightened question stored 20 results and about 100 KB. Results are
  checkpointed as each step completes, so this works mid-turn.
- **Turns are dated from the checkpoint** (`written_at`: the earliest
  checkpoint containing each message). Durations are measured in the browser,
  from send to stream end.

## Frontend

### Chat

- **Retry** sits on the last turn's question and answer (a failed turn
  stores no answer), only once the turn is over. Beside an error it is a
  "Try again" button; elsewhere a quiet icon.
- **Copy** is on every answer and copies the model's markdown with dotted
  ids, so a pasted note still says where it came from. The tick appears only
  once the clipboard write resolves.
- **Waiting looks like work:** an animated ellipsis (three elements, since
  animating `content` is not portable), a pulsing marker on running lookups,
  and an elapsed counter (tenths under 10s). All stop under
  `prefers-reduced-motion`.
- **The trace** gives each tool its own marker, puts the outcome in a
  right-aligned column, and replaces a dotted id with the heading the server
  resolved. Replayed conversations start collapsed.
- **Usage** shows the total; the in / out / calls split is on hover.

### Thread list

- Fixed width (`SIDEBAR`, 260px); collapses to a rail with expand and new.
- The row draws the box; the title button and the `⋯` button inside paint
  nothing (a button cannot contain a button). `⋯` shows on hover, focus or
  while its menu is open, and keeps its width so titles truncate in place.
- The row menu is `position: fixed` at its button, since the list scrolls
  and clips; scrolling closes it.
- **Delete** confirms in a native modal `<dialog>` (top layer, focus trap,
  Escape, backdrop). Cancel has focus: there is no undo. The dialog stays
  open if the request fails. Padding is on an inner element so a click on
  the dialog itself is a backdrop click.

### Side panel: the page

- The Page tab is a pdf.js render with highlight boxes from
  `/source/{id}`, so a citation is checkable against the printed page. With
  nothing cited it is the whole book, lazily rendered, with a page-jump box.
- **A citation shows its place in the book:** a breadcrumb from the
  top-level section down to the cited one (`ancestors`, read from the
  `HAS_SUBSECTION` path), every ancestor clickable, and its subsections
  listed below the page in book order.
- **A section is boxed with everything under it,** since its `char_end`
  covers every descendant: 16 pages for Rules Definitions, 87 for
  Monsters A-Z. So only the first page with boxes renders at once and
  scrolls itself into view; the rest have placeholders sized from page 1's
  aspect and render as they scroll near. (When every page scrolled itself
  into view, the last to render won, and the panel opened at a seemingly
  random page.)
- **Closing the panel clears the citation** (the close button or the active
  toolbar tab), so reopening it shows the whole book.
- **Width is the reader's choice:** a dragged handle (listeners on the
  window, 4px grip in a 13px target, a real grid column) with a remembered
  width, defaulting to half the window and clamped to leave the conversation
  420px, on load as well as resize. Zoom (Fit, 1.5x, 2x) is remembered too.
- **The page follows the panel width:** display size is derived from the
  observed width every frame; the bitmap re-renders only after the width is
  still for 150ms, drawn off screen and copied (resizing the visible canvas
  clears it). Rendered sizes are floored, and the stack's outline is a
  `box-shadow`, because one extra pixel at Fit adds a scrollbar.
- **Text layer CSS is ours,** scoped under `.pdf-stack`, not
  `pdf_viewer.css`, which injected the whole viewer's styles (`.sidebar`,
  `.error`, 376 `:root` variables including `--bg`) into the app. Three
  details it needed:
  - the variable is `--total-scale-factor`; with `--scale-factor` every span
    had `font-size: 0`;
  - selection tints with transparent text, since the default
    `HighlightText` made the invisible spans show as white glyphs;
  - `.endOfContent` (from pdf.js's `TextLayerBuilder`) covers the layer
    during a drag so a pointer in a gap does not select up to distant text
    in DOM order.
- **Highlights use `mix-blend-mode: multiply`** at full opacity, so paper
  takes the tint and ink stays black (a 62% translucent fill cut word
  contrast to about a third). `.pdf-stack` isolates the blending.
- **Panning above Fit** is Space+drag or middle-drag, because a plain drag
  selects text. It scrolls the figure horizontally and the panel body
  vertically. Space is ignored in typable elements and released on `blur`.

### Side panel: the graph

- The Graph tab shows the cited section's neighbourhood (default depth 1,
  remembered). Both tabs share the selected section; a node opens on the
  page, a subsection link re-seeds the graph.
- **Expanding merges** into the picture. A capped node shows a dashed halo;
  asking it for more requests twice its largest drawn group, since the server
  sample is deterministic and the same fan returns the same nodes.
- **The layout is ours:** an O(n^2) force simulation over at most 60 nodes,
  seed pinned at the centre, stopping once cool. Rest length comes from the
  panel area per node.
- **Fitting** bounds the labels (about 130 units wide), not the dots, never
  zooms below `FIT_MIN` (the picture overflows and is panned instead), and
  avoids the details card's measured height. The view is the user's after
  they pan, zoom or drag; `Fit` hands it back.
- **The details card** shows a node's summary (markdown and tables
  stripped) or, with no prose, up to six properties (`resources` rejoined).
  It lists a row per relationship type and direction with drawn vs total.
- **Colour comes from a priority** (`KINDS` in `graph-layout.ts`), most
  specific label first, since nodes are multi-label. `:Section` is never
  shown. An unlisted label draws grey, so `test_docs.py` checks `KINDS`
  against the mapper.
- **Filled nodes are sections; hollow nodes are derived,** so the
  "Alignment" section and glossary term do not read as a duplicate.
- Edge types are labelled only on the selected node's edges, at most five.

## Testing

- `uv run pytest`: backend. Graph and chat tests need a loaded Neo4j and
  **reload the configured database** (`TestLoadGraphAgainstNeo4j`).
- `npm test` in `frontend/`: vitest and Testing Library, no backend.
- `npm test` in `e2e/`: Playwright over Vite, FastAPI and a **fresh Neo4j
  container** loaded from this checkout's artifact (not the docker-compose
  database). Own ports (8001, 5174) and own `.data` directory, with `chat/`
  emptied each run. `CHAT_STUB=1` and a blank `GOOGLE_API_KEY`, so no quota
  is spent and search is lexical only. Needs Docker, the artifact and
  `srd_embeddings.idx`; skips without them. Running the development Neo4j at
  the same time can starve the browser of memory (macOS suspends its network
  service), so global setup warns; one retry covers it.

## Validation

### Stage 1: the book checks itself

- Index of Stat Blocks: 330/330 reconcile, 0 missing, 0 page mismatches,
  0 duplicates. The 6 "not in index" are summoned creatures absent from it.
- Damage averages: 697 checked against their own dice, 0 mismatches.
- Attack bonuses: 413 checked as ability modifier + proficiency bonus,
  0 mismatches.
- Ability modifiers, HP formulas, Initiative scores and passive Perception
  are cross-checked per stat block.
- Class spell lists vs spell subtitles: 338 spells on level, school, classes,
  concentration, ritual and specific material, 0 mismatches.
- Page geometry vs page range: every section has rectangles on the pages it
  claims (derived independently from page markers and lines).

Rules that cost debugging time:

- A passive score is `10 + bonus`, **plus or minus 5 for Advantage or
  Disadvantage.** The Invisible Stalker's `+7 (22)` is correct: it is
  permanently Invisible, which grants Advantage on Initiative.
- The `M` flag on class spell lists means a *specific* material component
  (with a cost or consumed), not any material component.

## Known source-document quirks

Reported, not corrected, except the first, where the rules-correct value is
used and the printed one kept in `printed_score`.

- **Gray Ooze** prints `Initiative −2 (13)`, implying Advantage nothing
  grants (it lost False Appearance in the 2024 revision). Uses 8 and warns.
- **Flaming Sphere:** subtitle says Conjuration, all three class lists say
  Evocation.
- **Mind Spike:** subtitle claims Sorcerer; it is on no Sorcerer list.
- **Phantasmal Force** is on no class list.
- **Young White Dragon** prints `Int 6 −2 2`, dropping the save's sign.
- **Create Undead** writes `one 150+ GP black onyx stone`, not `worth 150+ GP`.

## Not done yet

- Class spell lists produce `references_spell` from a `class_feature`; a
  `grants_spell` relation with class and level would be better.
  `ON_SPELL_LIST` (from each spell's subtitle) is the closest today.
- Fusion weights both arms equally. For "how much damage does a longsword
  do" the lexical arm's rank 1 ("One Thing at a Time") counts as much as the
  dense arm's correct rank 1. A per-arm weight or a Lucene score floor is the
  next step; `found_by` is there to measure it.
- Nothing reranks; a cross-encoder over the candidates is the standard next
  step.
- Spell mechanics are lighter than creature mechanics (no target shapes).
- No typed traversals for the recurring question shapes
  (`creatures_imposing(condition)`), which would be cheaper and more reliable
  than Cypher the model writes each time.
- `fan` widens every group at once; for complete lists the docstring points
  the model at `query_srd_graph`.
- The graph view opens only on a citation; there is no node search to start
  from.
- A cited section shows only its one or two pages, with no page-jump and
  no paging past the passage. The open question is whether a citation should
  open the whole book at that position, boxed, so the two states differ only
  by the highlight.
- The panel shows the PDF; nothing renders the markdown `/source` returns.
- No CI. A workflow needs an `srd-parse` step (the artifact is gitignored),
  a `neo4j:5.26-community` service for graph and chat tests, and a decision
  on `srd_embeddings.idx` (13 MB, gitignored, needs a key to generate):
  cache it by artifact digest or fetch it from a release.
- An embedded graph for contributors without Docker was parked: Kùzu is
  schema-first and single-label per node, so it would need a differently
  shaped graph. Everything except `test_loader.py` runs without Docker.
- One table is still misplaced relative to its heading (Apparatus of the
  Crab Levers, p210); the table itself is intact.
