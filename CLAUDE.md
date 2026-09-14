# dnd-graph-rag

Knowledge-graph RAG over the D&D 5e SRD (`SRD_CC_v5.2.1.pdf`, 364 pages).

Three stages, each meeting the next at one artifact. **Stage 1** turns the
PDF into `srd_hierarchy.json`, a self-validating document of typed entities
and the edges between them. **Stage 2** loads that artifact into Neo4j.
**Stage 3** answers questions from the graph and cites the book. Nothing in
`srd/` knows a database exists; nothing in `graph/` opens a PDF; nothing in
`chat/` writes to either.

This file documents all three: what they produce, how they are laid out, and
the reasoning behind the parts that are not obvious.

## Layout

A monorepo: `backend/` is the Python service, `frontend/` the React UI, and
`data/`, `docker-compose.yml` and `.env` are shared at the root. Every `uv`
command runs from `backend/`; `config.py` resolves `data/` and `.env` from
the repository root regardless of the working directory.

```text
data/
  source/            the SRD PDF; checked in, never written to
  output/            srd_hierarchy.{json,md,anchors.json}; reproducible
                     srd_embeddings.idx; reproducible only with a key, so it
                     is also shared as a file (DND_GRAPH_RAG_EMBEDDINGS)
  chat/              chat.sqlite (LangGraph checkpoints) and
                     chat-store.sqlite (pins); NOT reproducible

backend/src/dnd_graph_rag/
  config.py          pydantic-settings; DND_GRAPH_RAG_* paths, NEO4J_*,
                     CHAT_*, EMBED_*
  api.py             FastAPI: assembles each package's router
  srd/               stage 1 — PDF → artifact
    layout.py        PDF → ordered, styled text lines → markdown
    statblocks.py    lines → flat creature records
    mechanics.py     attacks, saves, damage, conditions imposed
    equipment.py     weapons, armour, adventuring gear
    character.py     classes, species, backgrounds, feats, poisons, damage types
    references.py    glossary terms and cross-reference edges
    pipeline.py      orchestration, entity typing, validation, CLI
    routes.py        /health, /parse, /pdf
  graph/             stage 2 — artifact → Neo4j
    model.py         typed node/edge batches; the mapper/loader seam
    embeddings.py    one vector per section, and the file they travel in
    mapping.py       document → batches.  Pure: no driver, no I/O
    schema.py        constraints, indexes, full-text and vector indexes,
                     reset
    loader.py        driver, batched UNWIND writes
    verify.py        post-load checks against the artifact's own counts
    pipeline.py      orchestration
    cli.py           srd-graph-load, srd-embed
    routes.py        /graph/health, /graph/load
  chat/              stage 3 — graph → answers
    retrieval.py     the graph, read.  Lexical search, dense search, the
                     two fused by rank, and one section by id
    cypher.py        the agent's own Cypher: the guard, the read-only
                     transaction, the derived schema, the rows rendered
    tools.py         the four of those the agent may call
    agent.py         LangGraph tool-calling loop on Gemini
    service.py       one turn → a flat stream of typed events
    source.py        a citation → its characters, and its page rectangles
    stub.py          a scripted model, for the suites.  Never a fallback
    neighbourhood.py the graph read as a graph: one node and what surrounds it
    routes.py        /chat, /chat/threads, /source/{id}, /neighbourhood

frontend/            React + Vite chat UI
  src/api.ts         the browser half of the SSE contract
  src/useChat.ts     conversation state for one thread
  src/useStored.ts   localStorage-backed state; guarded both ways
  src/components/    Markdown (clickable citations), ToolTrace (a marker
                     per tool, the outcome in its own column), Timing (when
                     a turn happened, and how long it is taking), SidePanel,
                     PdfPage (canvas + text layer + highlight boxes),
                     GraphView (force layout, expanded a node at a time)
                     over graph-layout.ts (the arithmetic, with no React in
                     it: the spring, the fit, the palette, the merge),
                     Resizer

e2e/                 Playwright over the whole stack: it starts the API, the
                     app and a Neo4j container of its own, loads the graph
                     from the artifact, and drives the flows a reader
                     performs.  `CHAT_STUB=1`, so no API key and no quota.
                     Skips without Docker or an artifact.

backend/tests/       one file per module, mirroring the package it covers:
                     tests/graph/test_mapping.py for graph/mapping.py.  Each
                     test is a method on a class named for the function under
                     test, written Given / When / Then.  Unit tests need
                     nothing; the ones wanting data or a database skip.
frontend/src/        tests sit beside the file they cover — api.test.ts for
                     api.ts — under vitest and Testing Library, in the same
                     describe-per-function, Given / When / Then shape.
```

## Configuration

`config.py` is `pydantic-settings`, reading `.env` and the environment.
`Settings` covers the paths (`DND_GRAPH_RAG_ROOT`, `_DATA`); `Settings.neo4j`
and `Settings.chat` are `@cached_property`, built on first access, so
`NEO4J_PASSWORD` being required never breaks `srd-parse`, which needs no
database, and `GOOGLE_API_KEY` being required never breaks either pipeline.
The paths are resolved inside `build()`/`load()` rather than frozen as
import-time argument defaults, so overriding an environment variable actually
takes effect.

`embeddings_path` lives on `Settings` and the rest of `EmbeddingSettings`
does not, for exactly this reason: reading the vectors off disk needs no API
key, so asking where they are must not require one. `DND_GRAPH_RAG_EMBEDDINGS`
overrides the path; `EMBED_MODEL`, `EMBED_DIMENSIONS`, `EMBED_TASK_TYPE`,
`EMBED_BATCH`, `EMBED_MAX_CHARS` and `EMBED_WRITE_BATCH` are the rest, and
`GOOGLE_API_KEY` is shared with the chat. A *blank* `GOOGLE_API_KEY` counts
as no key at all. It is how someone turns it off without deleting it, and
the only way to reach the offline path from a checkout that has one, since an
unset environment variable does not beat an `.env` that sets it.

`checkpoint_name` lives on `Settings`, not `ChatSettings`, for the same
reason: the server must be able to say where conversations are stored without
an API key, and reaching through `Settings.chat` to build the path made a
missing key kill startup for every endpoint.

## Running it

```bash
docker compose up -d neo4j                     # from the root; NEO4J_PASSWORD from .env

cd backend
uv run srd-parse                               # writes data/output/srd_hierarchy.{json,md}
uv run srd-parse --pdf other.pdf --out /tmp/x.json
uv run srd-embed                               # writes srd_embeddings.idx; needs GOOGLE_API_KEY
uv run srd-graph-load                          # artifact + vectors → graph, then verify
uv run srd-graph-load --no-reset --skip-verify
uv run srd-graph-load --embeddings ~/Downloads/srd_embeddings.idx
uv run pytest
uv run uvicorn dnd_graph_rag.api:app --reload  # http://127.0.0.1:8000/docs

cd ../frontend && npm install && npm run dev   # http://localhost:5173
npm test                                       # vitest, once
npm run coverage                               # the same, with v8 coverage

cd ../e2e && npm install
npm run install-browsers                       # once
npm test                                       # Playwright starts everything
```

The pipeline is importable and takes about 30 seconds:

```python
from dnd_graph_rag.srd import build, load
document = build()          # parse and write
document = load()           # read what was written earlier
```

`parse()` reports progress through an injected callable, so the CLI passes
`print` and the API passes nothing.

Each package owns its own routes in a `routes.py`, and `api.py` only
assembles them. None of those modules is imported by its package's
`__init__`, which is the invariant that matters: every stage stays runnable
as a script, so `from dnd_graph_rag.srd import build` pulls in no web
framework to do it.

### API

The API is a remote trigger for the same run, not a query layer. `POST /parse`
runs the pipeline in a worker thread and writes the identical JSON and
markdown the CLI writes; it returns `meta`, `validation` and the paths
written, never the document. Nothing is cached in memory — the artifact on
disk is the interface, and the graph loader reads that.

```text
GET  /health        paths and whether the PDF and output exist
POST /parse         {"pdf": ..., "out": ...}, both optional
GET  /graph/health  Neo4j reachability plus node and relationship counts
POST /graph/load    {"input": ..., "reset": true, "skip_verify": false,
                     "embeddings": ..., "refresh_embeddings": false}

POST /chat              {"message": ..., "thread_id": ...} → SSE
GET  /chat/threads      stored conversations, pinned first then newest
GET  /chat/threads/{id} one conversation's turns, for reopening it
GET  /chat/threads/{id}/lookups/{call_id}  what one lookup returned
PUT  /chat/threads/{id}/pin  {"pinned": true}; 404 if there was none
DEL  /chat/threads/{id} delete one conversation; 404 if there was none
GET  /source/{id}       the markdown behind a citation, ?context=400
GET  /neighbourhood     ?section= or ?node=, &depth &fan &limit
```

The Neo4j driver is synchronous, so the graph endpoints use the same
`run_in_threadpool` the parse endpoint does.

`/chat` is the exception to "the API is only a trigger": it is the
application. It still holds no state — `lifespan` opens one
`AsyncSqliteSaver` for the process and history lives there, addressed by a
thread id the browser holds. That is also what deleting a conversation
*is*: there is no thread table, so dropping the checkpoints drops the
thread, and `threads()` stops listing what has none.

**A pin is not something anyone said, so it does not live with what was
said.** `lifespan` opens a second store, `chat-store.sqlite`, beside the
checkpointer: the checkpointer's tables are LangGraph's to change, and a
pin outlives any particular turn stored next to it. Unpinning *deletes* the
row rather than writing `false`, because a pin is its own presence and the
value carries nothing the key does not — and deleting a thread deletes its
pin, which would otherwise be a row nothing reads and nothing cleans up.
The pins are merged into `threads()` rather than by the route, so the one
place that decides what the list *is* also decides its order.

**Each row's actions live behind `⋯`, inside the row rather than beside
it.** A button cannot contain a button, so the title and the `⋯` have to be
two elements; they must not *read* as two. The row carries the shape — the
padding, the corners, the hover, the selected tint — and the controls
inside it paint nothing of their own, so the eye gets one conversation with
a menu tucked into its right-hand edge. The `⋯`'s own hover is a tint of
`currentColor`, which sits inside the row's rather than competing with it,
and inherits the accent on the selected row.

Reading a conversation is what you do to one of these far more often than
pinning or deleting it, so the control is hidden until the row is hovered
or focused — a column of `⋯` reads like a list of things to act on rather
than a list of conversations — and it keeps its width either way, so the
title truncates in the same place whether or not the icon is showing and
nothing shifts under the pointer as it fades in. The menu is positioned `fixed` from the button that opened it,
because the thread list scrolls and clips and a menu nested in a row would
be cut off by the pane it lives in; that is also why scrolling closes it.

Delete asks first, in a native `<dialog>` at the centre of the screen:
there is no undo, and the target was an item in a menu that appeared under
the pointer a moment ago. `showModal` is what makes it a `<dialog>` rather
than a div — the top layer, so no stacking context can bury it, plus the
focus trap, the inert background, Escape and the backdrop, all of which are
a lot to hand-roll badly. The padding sits on an inner element so that a
click landing on the dialog itself is unambiguously a click on the
backdrop.

**Cancel** takes the focus, not **Delete**: with no undo, the key someone
presses without reading has to be the one that changes nothing, and Escape
and the backdrop agree with it. The dialog stays open if the request fails,
since closing it would leave the reader believing a conversation was
deleted that is still there. The routes reach it through
`request.app.state`, as a dependency, rather than closing over a module
global.

`/pdf` sits with stage 1 rather than with the chat that displays it: it
serves `settings.pdf_path`, which is stage 1's input. Each route lives with
the code behind it.

## Stage 3 — the chat

A LangGraph tool-calling agent (`langchain.agents.create_agent`) on Gemini,
with four tools: `search_srd`, a hybrid search over both indexes;
`get_srd_section` by dotted id; `explore_srd_graph`, the edges around one
section; and `query_srd_graph`, read-only Cypher. `service.stream_turn` flattens LangGraph's stream into small typed
events — `token`, `tool_start`, `tool_end`, `citations`, `error`, `done` —
which `api.py` encodes as SSE and a test iterates directly.

**The search has two arms, because they fail differently.** `srd_text` is
Lucene, so its ranking *is* BM25, and it cannot match a question that shares
no words with the book: "a creature lying on the ground can only crawl"
returns the Ring of Mind Shielding. `srd_vector` over the embeddings finds
Prone from that sentence, and cannot be trusted on an exact term, since Fire
damage and Cold damage sit next to each other in the space. Each arm is asked
for `CHAT_SEARCH_LIMIT` candidates; the fusion cuts the union to `CHAT_TOP_K`,
which is what the model reads.

**Fused by rank, not by score.** A BM25 score is unbounded and
corpus-relative, a cosine similarity lives in [-1, 1]; normalising them
against each other would be a fiction that ranks whichever arm happens to have
the wider spread. Reciprocal rank fusion asks each arm only what it can
actually answer — which of these did you like better. `fuse` is pure, so the
arithmetic is tested without a database, and `Passage.found_by` names the arms
a result came from, which is what makes a ranking inspectable rather than
something to take on faith.

**A query cannot come out of a file.** `srd_embeddings.idx` covers every
section of the book, so a *load* needs no key — but a question nobody has
asked yet has to be embedded when it is asked, under `RETRIEVAL_QUERY` rather
than the documents' `RETRIEVAL_DOCUMENT`. So `embed_query` returns `None`
without a key and the search is the lexical arm alone: narrower, and still
working. That is the one degradation in stage 3. Anything else that goes
wrong — a rejected key, a spent quota — is raised and reaches the reader as an
error, like the model's own failures. The vector is cached on the query text,
since a follow-up turn routinely repeats it.

**A dense index always has a nearest neighbour**, so "nothing matched" is no
longer something the search can say: with both arms live, a nonsense query
returns three irrelevant passages rather than a refusal. Judging whether they
are about the question is the model's job, and the prompt says so in as many
words. The no-match sentence survives for the case that can still reach it —
both arms empty, which is a checkout with no key.

**The graph tool is the other half of a citation.** `explore_srd_graph` runs
`neighbourhood` — the same bounded walk the Graph tab draws — and renders it
as prose. Two things make it usable rather than misleading. `truncated` is
spelled out, so a group reads "20 in the graph, 8 shown" instead of
presenting eight neighbours as the whole answer — and `fan` is an argument so a
reader of a sample can ask for more of it. The node budget rises with the
fan, because it is spent in discovery order and a fan raised against a fixed
limit widens the first group and starves the rest: an ask for more that
returns less. For a list that must be complete the docstring sends the model
to `query_srd_graph` rather than promising that a wide enough fan will do. And every neighbour
carries an id to cite.

**That last part is most of what makes the tool cheap.** The prompt asks for
an id after every claim and a `:CreatureAbility` has none, so a walk that only
*names* them is a list of things the model may mention and may not cite — and
it answers that by searching for each one by name, a call apiece. One extra
query resolves where each derived node was printed (`HAS_ABILITY` from the
stat block, `DEFINED_IN` to the defining passage) and the line reads `Roar
(3/Day) (CreatureAbility; printed in [15.146.3] Sphinx of Valor — cite that)`.
What is genuinely printed nowhere — a damage type, a weapon row — still says
*do not cite*, and an ability the query cannot place keeps its owner in the
name, because the book prints a dozen Swallows.

**The agent writes its own Cypher, because the exhaustive question has no
other answer.** A search returns passages and a walk returns a sample, and
the model treats both as leads to verify: "which creatures can make someone
Frightened" cost sixty-odd tool calls and was still a list assembled by
guesswork. It is one query, and `query_srd_graph` runs it.

**The boundary is the transaction, not a word list.** The session is opened
`READ_ACCESS` and the query runs in an explicit transaction, so Neo4j refuses
a write itself with `Neo.ClientError.Statement.AccessMode` before anything
happens. That is what makes the tool safe, and it is also why the obvious
denylist is not merely redundant but wrong: the SRD contains a spell called
*Create Undead*, so refusing any query containing `CREATE` would refuse
`WHERE s.name = 'Create Undead'`. What read access does *not* cover is
procedures — `CALL dbms.listConfig()` is a read, runs happily, and returns
the server's configuration — so those are allow-listed, with `LOAD CSV`
refused beside them. The guard cuts string literals out before it reads
anything, so a rule about Cypher never becomes a rule about the book. Two
bounds finish it: a row cap, which is what the model reads, and a
transaction timeout, which is what the row cap cannot do, since a cartesian
product costs its time server-side before it sends a single row.

**The schema is derived, and it is in the prompt.** `shapes()` reads which
labels each relationship actually joins off the data — one pass over 11442
relationships, 0.14s, cached for the process — because a schema written down
in a prompt drifts from `mapping.py` the first time anyone edits it and
nothing fails: the model simply writes Cypher against a graph that no longer
exists. `db.schema.visualization` would be the obvious source and is not, since
it reads the token store and on a multi-label graph reports combinations no
node has. Beside it sit the ten or so facts no introspection can state —
nodes are multi-label, the dotted `id` is the only citable identifier, a
creature *is* its section and an ability is not. It goes in the system prompt
rather than behind a tool because the model has to know the labels at the
moment it composes a query; a schema tool costs a round trip on every turn
that touches the graph and two on every turn that guesses wrong. A graph that
cannot be reached costs the schema, not the turn.

**Two lines of the orientation block are worth more than the tool was.**
Measured on "which creatures can make someone Frightened", five runs an arm:
the schema as first written gave a median of 29 tool calls, and adding the
*idiom* — that an effect reaches its target through an intermediate node, so
a creature imposes a condition both through its ability and through a spell
that ability casts — took it to 12. The labels were never the problem. The
model had them and used them correctly from the first query; what it lacked
was which *chains* answer which kind of question, and that is a fact about
how this graph models the book rather than anything introspection can report.

**And the rest of the calls were a cell cap.** With the paths named, what
remained was twenty `get_srd_section` calls a run, one per row: the answer
needs "DC 13 Wisdom saving throw, Frightened until the start of its next
turn", `CELL_CHARS` was 200, and 22% of ability descriptions are longer than
that — the *interesting* 22%, since a trait with a saving throw and a
duration is longer than a trait without. The model was reading truncated
mechanics and going to fetch the rest of a column it had already been given.
At 600, which cuts 18 of 1314, the median is 8 calls and most runs never open
a section at all. A `TOTAL_CHARS` budget bounds what the cell cap no longer
does, dropping whole rows rather than squeezing cells, because a
half-populated row reads as a fact about the book.

**An error is a result, not a failure.** A bad label or a backwards
relationship comes back as the message plus a pointer to the schema, and the
model fixes it and runs again — the loop working. Only `AccessMode` is
reworded, because Neo4j's own text for it is "Unexpected error has occurred.
See debug log", which tells the model nothing it can act on.

**Filled is printed, hollow is derived — and that costs a hop.** A citation
names the *section* defining Prone; the `:GlossaryTerm` that 58 things
`IMPOSES_CONDITION` is one hop further out. So depth 1 from a citation often
shows only structure, and the tool's own docstring tells the model to walk it
again at depth 2 when it does.

**The model is required, and a failure is the reply.** There used to be a
`fallback.py` here that answered from graph search alone when the model could
not be reached — offered beside the error, or substituted outright under
`CHAT_FALLBACK=always`. It is gone. An unsummarised list of passages is a
useful thing to read and a dishonest thing to hand someone who asked a
question, and a way out of a failure makes the failure easy not to fix. So a
turn that cannot reach the model, cannot finish, or is refused by it ends
with an `error` event saying which, and nothing else.

The three failures that actually happen are named by `_explain`: no key, a
rejected key, a spent quota. A *missing* key is the one knowable before the
response is committed, so `POST /chat` builds the agent first and answers
**503**; everything that can only fail mid-call arrives as the in-band
`error`, because by then the stream has already announced itself as a turn.
A blank `GOOGLE_API_KEY=` counts as missing, on both `ChatSettings` and
`EmbeddingSettings`, so turning the key off reads as the sentence naming
`.env` rather than as Google rejecting an empty credential.

**The suites still need an answer, and that is a seam, not a fallback.**
`chat/stub.py` is a scripted `BaseChatModel` — call `search_srd`, then cite
the first id that comes back — selected by `CHAT_STUB`, which the backend's
route tests and the whole of `e2e` set. The agent loop, the tools, the graph,
the streaming and the citations are all the live ones; only the sentences are
fake. Nothing turns it on in response to a failure, which is the entire
difference between it and what it replaced. It lives in the package rather
than in `tests/` because e2e drives a real uvicorn subprocess, which can only
be steered by the environment.

**A hang is not an error, and that was the hole.** A stalled call is
indistinguishable from a thinking one from out here: it never yields, never
raises, and so never fails at all — the turn simply hangs, with no answer
and no error. `_until_silent` fails the turn
after `CHAT_TIMEOUT_SECONDS` of *silence*, reset by every token and every
tool result, so it bounds nothing but quiet.

**The error is now the answer, so it has to be readable.** A provider error
is JSON with the sentence buried in it — the invalid-key one is 600
characters carrying "API key not valid" twice. The three that actually
happen (no key, a rejected key, a spent quota) are named, and anything else
is capped at a length someone will still read.

**The trace shows the retrieval, which means three things and not one.**
A row per tool call, all drawn as identical muted dots, said only that a call
had happened. It hid *which kind* of lookup it was, and a ranked fuzzy search,
an exact query over the whole graph and a fetch of one section by id are
different operations: drawn the same they make an agent that is reasoning look
like one repeating itself. It hid *how it went*, so a refused procedure and a
perfect query drew the same grey dot. And it hid *what came back*, so three
passages and none were the same line. Each tool now carries a marker of its
own, the outcome sits in a right-hand column where a run of them can be
scanned without re-reading the labels, and a dotted id is replaced by the
heading it names, because `10.3.165` tells a reader nothing.

**A reopened conversation keeps its trace.** `history` used to read only the
human messages and the final answer, skipping every assistant message that
carried tool calls, so a conversation opened from the thread list showed its
answers with no retrieval under them: the trace read as something that had
never happened. Everything needed was already in the checkpoint, since the
calls are on the assistant messages that made them and the status and summary
ride on the tool results that answered them. `turns_of` is pure, so the part
that decides which lookups belong to which turn is tested without a database
or a model, and a turn that ended in an error does not lend its lookups to
the question after it.

A conversation answered *before* the tools carried an artifact has only the
dotted id it was called with, so `name_missing_subjects` asks the graph what
that id names, which is the same lookup `resolve_citations` makes a few lines
above for every citation. Only the subject is recovered: a count of what came
back cannot be, short of running the search again, so those rows stay blank
rather than claiming a number nobody recorded.

**Opening a row shows what the lookup returned, fetched on demand.** The
results are all in the checkpoint already, since a tool result is a message
like any other, but one turn of the Frightened question stored twenty of them
and a hundred kilobytes of table, almost none of which anyone opens. So the
conversation carries counts and `GET /chat/threads/{id}/lookups/{call_id}`
carries the rest, one row at a time, cached for the life of the trace. It
serves a turn still on screen as readily as a reopened one: a tool result is
checkpointed as soon as its step completes, which is before the row it
belongs to is drawn as finished. A query shows the Cypher above its rows,
because a result only means something beside the question that produced it.

**The outcome travels as an artifact, not in the result.** The tools return
prose because the model reads it, so the status and the one-line summary go
back as LangChain's `content_and_artifact` pair: it rides on the
`ToolMessage`, `service` puts it on `tool_end`, and the model never sees it.
That is the same split the tool results already use, and it is why the trace
can distinguish `empty` from `failed` without either the model or the browser
parsing our own prose. `empty` is its own status on purpose: a query matching
nothing is an answer about the book, not a broken tool.

**A long wait has to look like work.** An agentic turn is quiet for a whole
round trip before it says anything and for eight of them on a hard question,
so a static "Thinking…" is indistinguishable from a hang. The ellipsis is
three elements whose opacity animates rather than an animated `content`
string, which browsers disagree about; the marker on a running lookup pulses
on the accent; and the wait counts up beside them, in tenths under ten
seconds and whole seconds above, where a tenth is noise on a number that is
already the headline. All of it stops under `prefers-reduced-motion`.

**Every turn is dated, and the date comes from the checkpoint.** `written_at`
reads the `ts` the checkpointer stamps on each step and maps it by message
id: `alist` yields newest first, so overwriting as it goes leaves the oldest
sighting of a message standing, which is the moment it was written. That is
what makes a reopened conversation dated by when it happened rather than by
when it was read. The *duration* is the browser's, measured from pressing
send to the stream ending, because that is the wait somebody actually sat
through rather than the span between two server writes.

**Citations are driven by the answer, not by the search.** The system prompt
asks for `[11.2.114]` after each claim; `resolve_citations` parses those ids
out of the finished text and looks each one up. So the citation list is what
the answer actually leans on, and an id the model invented resolves to
nothing and is dropped rather than rendered as a dead link. Listing what was
retrieved instead would credit passages the answer ignored.

**`char_start`/`char_end` are the whole payoff.** `GET /source/{id}` slices
`srd_hierarchy.md` at the offsets the graph carries, and returns `highlight`
as offsets *within the returned slice*, so `?context=400` can show the cited
passage in its surroundings and still dim everything that is not it. This is
the reason stage 2 folds an entity into its section instead of copying it: a
copy would have no offsets to slice by.

**The same offsets reach the printed page.** `lines_to_markdown` already
computed every line's rectangle on its way to producing the markdown, and
used to throw it away. It now emits an *anchor* per part — the character
range it occupies plus the page and box of each line behind it — written to
`srd_hierarchy.anchors.json`. `section_boxes` bisects that for a character
range, so `/source/{id}` returns `boxes`, and the UI draws them over a
pdf.js render of the page. A citation is therefore checkable against the
book itself, not only against what the pipeline derived from it.

The geometry stays on disk and out of the graph: it is per-line and nested,
exactly the shape `clean()` rejects, and nothing traverses it. It is read
the way the markdown is read.

**A line's box comes from its baseline, not its bbox.** On a typical page
PyMuPDF reports 95 of 107 lines as 56pt tall — the same inflation that makes
the whole pipeline sort by baseline rather than by bbox top. The box is
`baseline - 0.80·size` to `baseline + 0.24·size`; horizontal extent *is*
trustworthy, since column detection and table cells already rely on it.

**How wide the page needs to be is the reader's question, not ours.** It
depends on their screen and their eyes, so the panel is a dragged control
with a remembered width rather than a constant, and the page zoom is
remembered beside it. The default width is proportional — half the window,
clamped — because the page is rendered *to fit the panel*, so the panel's
width is the reading size; a fixed default would be a thumbnail on one
screen and half the desk on another.

Both edges are the same component; only which direction "wider" points
differs. Neither can be clamped alone — they share a window, so each is
clamped against what the other is already taking, leaving the conversation
at least 420px.

The drag listens on the *window*, not on the handle: a pointer routinely
leaves a 13px target mid-drag and the drag must not stop when it does. The
grip is drawn 4px and grabbed 13px — easy to see, miserable to hit
otherwise. Each handle occupies a real grid column rather than overlapping
its neighbour with a negative margin, which resolves the track to 0px while
the element still paints 13px.

**The text layer's CSS is ours, not `pdfjs-dist/web/pdf_viewer.css`.** We
use `TextLayer` and nothing else, but that file is the entire viewer chrome:
it defines its own `.sidebar`, `.resizer` and `.error`, plus 376 custom
properties on `:root` — one of them `--bg`. Because `PdfPage` is lazy, the
whole thing was injected the first time a citation was opened and never
removed, so this app silently restyled itself mid-session: the thread list
turned white and took pdf.js's `--sidebar-width: 239px` and
`--sidebar-max-width: 632px`, and stayed that way after the panel closed.
`index.css` now carries the ~30 lines `TextLayer` actually needs, scoped
under `.pdf-stack`.

That import also hid a second bug. The rules read `--total-scale-factor`;
we were setting `--scale-factor`, which is nothing to them. Every span was
`font-size: 0`, so the page looked right and selection landed nowhere. With
the correct name a heading's span overlaps the box drawn for it by 97%,
which is the check worth keeping: the *selectable* text under a highlight
must be the text that was cited.

**Fitting must actually fit.** At Fit the canvas is exactly the container's
width, so two things that would each add a pixel are removed: the rendered
size is floored rather than rounded, and `.pdf-stack`'s outline is a
`box-shadow` rather than a `border`, since the stack is sized by
`max-content` and a border would widen it. Either one alone puts a
horizontal scrollbar under every fitted page.

**`.pdf-stack` takes its width from the canvas.** Above fit-to-width the
page is wider than the panel, so the stack must size to the canvas and let
the figure scroll it — and the render must therefore measure the *figure*
for its fit width, never the stack, which would be circular.

**The Graph tab is the same citation asked a different question.** The page
says what the book printed; `/neighbourhood` says what that passage is
connected to. Both tabs share the selected section, so switching never loses
the reader's place, and either hands the other a new one — a node opens on
its page, a subsection link re-seeds the graph.

**It never draws the whole graph.** 4260 nodes is a hairball, and one hub is
enough to swamp the panel on its own: `:DamageType {name: 'Poison'}` has 195
edges. So the answer is bounded three ways at once — `depth` hops from the
seed, `fan` neighbours per relationship type *per direction* per node, and
`limit` nodes in total. What the caps cut is counted in `truncated` rather
than dropped in silence, so a reader is told "121 creatures reference Poison
damage, here are 8" instead of being shown 8 and left to assume that is all
there is. A capped node is drawn with a dashed halo and expands on click,
merging into what is already on screen rather than replacing it, so
following a chain reads as walking rather than as a series of unrelated
pictures. Asking a capped node for more requests twice whatever is already drawn from
its largest group rather than repeating the request: the sample is
deterministic, so an identical ask returns the identical neighbours and
reads as a broken button. Deriving the number from the picture rather than
from a click count is what makes the *first* click work too — a node two
hops out was already sampled at the default fan on the way in.

**The sample is the best-connected of each group, not the first
alphabetically.** Rules Definitions has 155 subsections; by name it is
always the same eight entries beginning with A, each of them a leaf, and the
picture says nothing. By degree the same eight reach Prone, Petrified,
Fire damage — the parts of the book everything else points at, which is the
question a graph view is being asked. The name breaks ties, so the sample
stays deterministic and a repeated request returns the same nodes.

**How deep is the reader's question, not ours** — the same argument the panel
width is a drag handle for. Three is a screenful before anything is clicked
and two is most of one on a hub, so one hop is the remembered default: what
the citation is directly joined to, which is the question being asked on
arrival. Going further is a click away, and the control sits in the panel
header beside where the zoom buttons sit for the page.

**A node is addressed by `elementId`, not by section id.** A citation names a
section, but the interesting neighbours are not all sections — an ability is
keyed on `key`, a damage type on `name` — so there is no one property to
address them all by. The element id is stable for as long as the load is,
which is the life of anything looking at it; a re-load invalidates the ids
exactly as it invalidates the picture. That is why the endpoint takes
exactly one of `section=` (how a citation gets in) and `node=` (how a drawn
node expands).

**The budget is spent in discovery order, and an edge whose far end did not
fit is dropped with it** — an edge to a node that was never returned draws as
a line into nothing. For the same reason a row anchored at a node the budget
refused is skipped rather than drawn from thin air. `assemble` is pure so
that the part with the off-by-one in it is tested without a database.

**The layout is ours.** A force simulation over sixty nodes is a hundred
lines and no dependency; `d3-force` would be the whole library for the one
function of it we want. The seed is pinned at the centre — the reader came
here from a citation and the thing they cited should not wander off while
they watch — and the simulation cools and stops rather than repainting sixty
circles for ever behind an idle reader. Velocities stay in a ref because
they are the simulation's business; positions are published to state each
frame, so the picture is a function of state like everything else.

**The spring's rest length is not a constant.** Twelve nodes in a tall panel
and sixty in a short one want very different pictures, so the rest length
comes from the room available over the number of nodes, and the repulsion
that balances it follows from that.

**Fitting is not zoom, and lengthening the edges alone decrowds nothing.**
Scaling the layout up scales the circles and the labels with it, and the fit
then scales the whole thing back down: the two cancel exactly. What is
actually crowded is the *names* — a node is a dot about 11 units across with
a name beside it about 130 units wide — so the fit bounds the labels rather
than the dots, and stops shrinking at `FIT_MIN` rather than squeezing a
dense graph into an unreadable one. Past that the picture overflows and is
panned: legible and partly off-screen beats complete and unreadable.

**And it fits around the furniture.** The details card floats over the
picture, so the space it covers is not space to lay out in — fitting into
the whole canvas leaves the two or three furthest nodes drawn and invisible
behind it. Its height is measured rather than assumed, because it grows a
row per relationship type on the selected node.

The framing is ours only until the reader pans, zooms or drags a node;
after that it is theirs, and refitting under their hands would be the
application arguing with them. `Fit` hands it back, and has to recompute
the view rather than only clear the flag — by the time anyone reaches for
it the simulation has cooled and stopped, and there is no next frame.

**A node says what it is, in the card.** Selecting one answers "and what is
that?" in place rather than sending the reader to the Page tab and back:
`content` on a node that is a section, `description` on one the loader
derived — between them every node with prose. It arrives with the node, so
selection costs no request.

Three things that took the summary from useless to readable. The content is
*markdown*, so the SRD's own emphasis arrives as `**_Restricted
Movement._**` mid-sentence; the markers are typography rather than words and
are stripped. A section that is a **table** — the Mysterious Deck is a
hundred-row draw table — reads as `1d100 1d100 | (13-Card | (22-Card |` and
says nothing, so table rows are cut, and a summary with nothing left of it
is `None` rather than noise. And cutting the rows **strands the headings**
printed above them; what identifies one is not that it is short (a stat
block opens with "Medium Undead, Neutral evil", which is short and is the
most useful line it has) but that a table follows it.

**A node with no prose says what it does carry.** A Dagger is a table row: a
cost, a die, a weight, and not one sentence anywhere in the book. Listing
its properties beats an empty card and beats inventing a description. The
long text fields are named out of that list — a stat block's `content`
fetched a second time per row is the one thing here big enough to matter —
and the facts ride along only when they are what will be shown, so a
creature's forty properties never cross the wire. `resource_names` and
`resource_values` are put back together on the way (`Rages 3, Rage Damage
+2`): the mapper split them because Neo4j stores no nested maps, and side by
side they read as noise.

**Edge types are counted, not repeated.** Labelling every edge of the
selected node wrote `has_subsection` ten times across the same picture. The
type now goes on the edge only when there are few enough to read, and the
details card carries the real answer — a row per relationship and direction,
drawn against total, which is where a hub becomes legible: the picture can
honestly show eight of Poison's 121 references, but only a count can say
that it is 121.

**Colour comes from a priority, not a lookup.** Nodes are multi-label by
design — `:Section:Rule:Equipment:Poison` is one real node — so `kindOf`
walks a most-specific-first list: being a Poison says more about a node than
being Equipment does. `:Section` is dropped everywhere it appears, on the
node's labels and in the legend both: it is on 2368 nodes and says nothing
about which one this is. A label missing from that list is not an error
anywhere — the node simply draws grey — so `test_docs.py` reads the table
out of `graph-layout.ts` and holds it against the mapper, the same way it
holds GRAPH.md against it.

**Filled is printed, hollow is derived.** A node with a `section_id` is a
passage of the book; one without is something stage 2 derived from a
passage. Without the distinction "Alignment" and "Alignment" sit side by
side — the glossary *section* and the glossary *term* `DEFINED_IN` it — and
read as a duplicate rather than as two things. It is also the difference
that decides whether "Open page" is offered at all.

**Parameters go to Neo4j as a dict, never as keywords.** One of them is
called `query`, which is also `Session.run`'s own first argument.

**The tools return prose, not JSON.** The model reads them, and it cites what
it can see, so every result leads with `[id]`. The structured half reaches the
UI by another route — `service` reads tool calls off the message stream — so
nothing has to serialise for two audiences at once.

## Output

`data/output/srd_hierarchy.json` — `meta`, `sections` (tree), plus flat
collections and `validation`. `srd_hierarchy.md` is written beside it so every
node's `char_start`/`char_end` resolves to real text.

| Collection | Count | Notes |
| --- | --- | --- |
| sections | 2368 | tree, every node typed with `entity_type` |
| creatures | 336 | stat blocks, with structured mechanics on 706 entries |
| equipment | 146 | 38 weapons, 13 armour, 81 gear, 14 poisons |
| classes | 12 | core traits, 20-level progression, 232 features, subclasses |
| species / backgrounds / feats | 9 / 4 / 17 | |
| glossary | 172 | 15 conditions, 13 damage types, 12 actions, 4 poison types, … |
| references | 5255 | typed edges between all of the above |

Every section node carries an `entity_type`, and where a section *is* an
entity the metadata is attached to it rather than to a copy beside it:

| `entity_type` | Count | Carries |
| --- | --- | --- |
| `class_feature` / `rule` | 446 / 361 | prose |
| `spell` / `magic_item` | 343 / 265 | a `spell` / `item` block |
| `creature` | 336 | its stat block, one per section |
| `equipment` | 194 | 81 of them are the gear items themselves |
| `creature_group` | 189 | `members`, the stat blocks in its subtree |
| `glossary_term` | 155 | `term` and `term_type` |
| `origin` / `feat` / `front_matter` | 32 / 24 / 3 | prose |
| `environmental_effect` / `trap` / `contagion` | 9 / 8 / 3 | prose, typed as a set |

Gear and poisons name the section that prints them in `section_id`, so the
loader can fold them in rather than storing the same paragraph twice; weapons
and armour have no `section_id`, because they are only ever table rows.

## The graph

`srd-graph-load` reads the artifact and writes 4260 nodes and 11442
relationships. The load is idempotent — everything MERGEs on a stable key —
but a full reset is the default, because the artifact is the whole truth and
merging alone would leave behind nodes a re-parse has since dropped.

| Label | Key | Count |
| --- | --- | --- |
| `:Section` | `id` | 2368, one per tree node |
| ` + :Spell` / `:MagicItem` / `:Creature` / `:Rule` / `:ClassFeature` / … | `id` | 343 / 265 / 336 / 361 / 446 / … |
| ` + :Trap` / `:EnvironmentalEffect` / `:Contagion` | `id` | 8 / 9 / 3 |
| `:CreatureAbility` | `key` | 1314 traits, actions, reactions |
| `:GlossaryTerm` + `:Condition` / `:DamageType` / `:PoisonType` / … | `name` | 172 |
| `:Equipment` + `:Weapon` / `:Armor` | `name` | 51 rows with no prose |
| ` + :Gear` / `:Poison` folded into their sections | `id` | 81 / 14 |
| `:Class` / `:Subclass` / `:ClassLevel` | `name` / `key` / `key` | 12 / 12 / 240 |
| `:Species` / `:Background` / `:Feat` / `:Trait` | `name` / `key` | 9 / 4 / 17 / 61 |

Relationships are the artifact's own eight `references` relations uppercased
(`IMPOSES_CONDITION`, `REFERENCES_SPELL`, …), the structural ones
(`HAS_SUBSECTION`, `HAS_ABILITY`, `HAS_FEATURE`, `HAS_SUBCLASS`, `AT_LEVEL`,
`GRANTS_FEATURE`, `HAS_TRAIT`, `DEFINED_IN`), and a small derived set that
was already implied by parsed list fields: `IMMUNE_TO`, `RESISTANT_TO`,
`VULNERABLE_TO`, `IMMUNE_TO_CONDITION`, `ON_SPELL_LIST`, `CARRIES`,
`HAS_POISON_TYPE`, `GRANTS_FEAT`.

## Why it is built this way

**The section tree is the spine, and entity types are extra labels.** A spell
is not a `:Spell` node beside its section — it *is* the section, with a second
label. That keeps `char_start`/`char_end` on every entity, so anything a
traversal finds resolves straight back to its text in the markdown, which is
what makes the graph usable for retrieval rather than only for counting. The
dotted section id is the artifact's only globally unique stable identifier, so
it is the key.

**A closed set the book introduces gets a type.** Traps, environmental
effects and contagions were `rule` sections indistinguishable from the prose
around them, even though their text already carried the damage and condition
edges — so "which traps deal Poison damage" had nothing to select on.
`ENTRY_SET_ENTITY_TYPES` names the introducing heading; the entries are its
children where the book nests them ("Example Traps") and its following
siblings where it does not ("Example Contagions", printed at the same level
as the three it introduces).

**An entity that is its own heading folds into it.** A stat block *is* its
section (336 on both sides, names unique), and so is a gear item or a poison,
which the book prints as a heading with prose. Each folds in, adding its
labels and properties to that node. Anything else would store the same
paragraph twice and draw every edge from it twice over — which is exactly
what happened before `extract_gear` and `extract_poisons` recorded their
`section_id`: 95 duplicated nodes and 60 duplicated reference edges, and
"which things deal Poison damage" counted Serpent Venom twice.

Weapons and armour do not fold, because they are only ever table rows. Nor do
the flat collections that are not 1:1 with a section — all thirteen damage
types come from one table and share the section id `11.2.46.1` — so those
stay separate nodes joined by `DEFINED_IN`.

**Abilities are nodes because references point at them.** A creature-sourced
reference names the entry it came from in `part` (`actions/Bite`), so
`:CreatureAbility` is keyed `Goblin|actions/Bite` — the same string. Without
that, all 1582 of those edges would smear across the whole stat block and
"which creatures can Frighten, and *how*" would lose the second half.

**Targets are matched, never merged.** A reference target carries a name and a
type but no id. Merging on a name that fails to resolve would invent an empty
node and hide exactly the drift this stage exists to catch, so unresolved
targets are counted and reported instead. All 5255 currently resolve.

**A closed vocabulary becomes nodes; a bare classification does not.** The
thirteen damage types earn `:DamageType` nodes because 1987 edges point at
them from all over the book. Poison delivery types earn `:PoisonType` nodes
for the opposite reason: *nothing* refers to them, so without the
`HAS_POISON_TYPE` edge from each poison, the paragraph defining what
"Injury" means would be unreachable from the poison it describes. Both are
extracted the same way — one passage defining the whole set, so neither is
1:1 with a section and both live in the glossary rather than the tree.

**The embeddings are generated once, or not at all.** The text changes only
when `srd-parse` changes, so embedding is a property of the load rather than
of a turn. `srd-embed` writes `srd_embeddings.idx` and `srd-graph-load` reads
it; between them `EMBEDDING_QUERY` is a pass of its own after the nodes, so
`mapping.py` stays a pure function of the document with no knowledge of a
vector, `clean()` never walks 1536 floats per row, and the vectors can be
refreshed without reloading the graph.

**And they are required.** Either they are generated or they are supplied;
there is no `--no-embeddings`. A load that can do neither raises
`MissingEmbeddings` *before a session is opened*, so the previous graph is
left standing rather than reset and then abandoned, and the message names
both ways out, because it is the one thing between a reader and a working
graph. The check in `verify` counts sections with prose from the *document*
rather than from the file, which is what makes it a check rather than a
tautology: a stale `.idx` whose keys no longer match a re-parse fails there.

**The file is 40 lines of `struct` and `array`, not FAISS.** A FAISS index is
an ANN *search* structure and `srd_vector` is already that one; FAISS has no
string keys, so it would need a second sidecar for the id map, and reading it
would force a large platform-specific wheel on everyone for a file we iterate
exactly once. `array('f').tolist()` is already the `list[float]` the driver
wants, so numpy would buy a dependency and no conversion. Magic, a JSON
header, then raw little-endian float32.

**The header is what makes it a cache as well as an artifact.** It carries a
digest of each section's embedded text, so a re-parse that changed twelve
sections re-embeds twelve rather than 2156, and a file made under a different
model, width or task type is discarded *whole* rather than merged: two
vector spaces mixed in one index would rank nonsense without ever failing.

**The ancestors lead the embedded text.** The book has dozens of sections
called "Traits" and "Actions", and the tree is the only thing that tells them
apart: `Monsters > Goblin > Actions` is the thing someone is searching for
and `Actions` is noise. Truncation to `EMBED_MAX_CHARS` happens before the
digest, so the digest describes what was actually sent.

**Nested values fail at map time, not mid-load.** Neo4j stores primitives and
homogeneous arrays only, and the artifact is full of nested dicts. `clean()`
raises naming the offending *field*; Neo4j's own error names only the value.
A damage list becomes three parallel arrays (`damage_dice`, `damage_types`,
`damage_averages`) since its components correspond by position, and a
`resources` map becomes `resource_names`/`resource_values`.

**`mapping.py` touches no driver.** The entire JSON → graph translation is a
pure function of the document, so it is unit-tested without Docker and
`loader.py` shrinks to batching and transactions.

**Line-level layout, not `pymupdf4llm`.** The SRD is two columns. PyMuPDF's
reading order merges paragraphs into blocks and sometimes sorts a
bottom-of-column fragment after the whole facing column, which detached a
creature's `AC / Initiative / HP / Speed` line from its stat block and
silently gave it to a neighbour. Working at the line level, ordering by text
*baseline* (bbox tops are inflated by font metrics), fixed that.

**Columns are measured, not assumed.** Frames come from the empty vertical
strips between them, then get snapped to the grid the book as a whole uses —
342 of 364 pages are the standard two columns, the contents run three and
four. A table that spans the gutter hides the strip, so a page whose frames
are all grid columns adopts the full grid.

**Tables are rebuilt from x positions.** Most SRD rows have no ruling lines,
so PyMuPDF's table finder sees only the shaded ones. It is used for the
*region* only; cells come from the exact x positions of the text, which the
book aligns precisely. Rows just outside the detected rectangle are reclaimed
(`_absorb_edge_rows`) — that recovered 583 fragments across 160 tables.

**A stat block is a card, not a heading.** Its title, defence line, ability
grid and actions are one visual unit that the surrounding headings only
loosely describe. Parsing it as a unit, keyed off its distinctive 14.8pt
title, is what makes the result safe to turn into graph nodes. Stat block
titles are emitted at the deepest heading level so a creature summoned by a
spell cannot outrank the spell descriptions around it.

**Typography carries structure.** Heading level comes from font size;
`GillSans-SemiBold` at 26/18/14/12/10.5pt is H1–H5. Stat block section
headers ("Traits", "Actions") are *plain* GillSans 12, which is what
separates them from real headings. Small-caps sidebar headings extract as
mixed case ("rEstinG") and are recased.

**A list of names is one mention each.** The book routinely names several
things at once — "the Deafened and Frightened conditions", "Bludgeoning,
Piercing, and Slashing damage" — and the phrase matcher was built for a
single name before a singular noun, so it read none of them: 43 such phrases
went unlinked and the Tarrasque's Thunderous Bellow referenced no condition
at all. Lists are read generously here, *or* included, because these are
mentions and the text does name every one of them. Whether a condition is
*inflicted* is the stricter question below, and it reads only *and*: "a
creature that has the Grappled, Incapacitated, or Restrained condition" is
target eligibility, and guessing between the two readings would put the false
positives in the graph, which is what this stage exists to prevent.

**Edges come from the book's own markup.** Spells and magic items are
italicised, creatures bolded. A span becomes an edge only when it resolves to
an entity we actually extracted — italic is also emphasis and book titles.
Conditions, actions and damage types are not marked up, so they match on
required phrasing (`Prone condition`, `Utilize action`, `Fire damage`), which
keeps `Cover`, `Attack` and `Force` from firing as bare nouns.

**`imposes_condition` vs `references_condition`.** Typography only says two
things are mentioned together, and a stat block routinely imposes a pair at
once ("the target has the Deafened and Frightened conditions"), which a
pattern reading one name before a singular noun misses entirely. Direction comes from `mechanics.py`, which
scopes negation to the clause after the last comma, semicolon or full stop:
*"While Charmed, the target has the Incapacitated condition"* imposes it,
*"while the vampire has the Incapacitated condition"* does not, and *"one
creature that has the Prone condition"* is target eligibility.

## Validation

### Stage 1 — the book validates itself

The run fails loudly rather than silently:

- **Index of Stat Blocks** — an independent list of every creature and its
  page. Reconciles 330/330, 0 missing, 0 page mismatches, 0 duplicates. The 6
  "not in index" are summoned creatures genuinely absent from it.
- **Damage averages** — 697 checked, each must equal the average of its own
  dice. 0 mismatches.
- **Attack bonuses** — 413 checked, each must equal an ability modifier plus
  the proficiency bonus. 0 mismatches. This is a joint check: it only holds if
  the mechanics parse, the ability grid *and* the proficiency bonus are all
  right at once.
- **Ability modifiers, HP formulas, initiative scores, passive Perception** —
  all cross-checked per stat block.
- **Class spell lists vs spell subtitles** — 338 spells cross-checked on
  level, school, class set, concentration, ritual and specific-material.
  0 mismatches.
- **Page geometry vs page range** — every one of the 2368 sections must have
  rectangles, and they must fall on the pages the section claims. The two
  are derived by different routes — the range from the `<!-- PAGE:n -->`
  markers, the boxes from the lines themselves — so agreeing means both
  describe the same passage. 0 without geometry, 0 misplaced.

Two rules that cost real debugging time:

- A passive score is `10 + bonus`, **±5 for Advantage/Disadvantage**
  (Rules Glossary). Missing that flagged the Invisible Stalker as broken when
  its `+7 (22)` is correct — it is permanently Invisible, which grants
  Advantage on Initiative.
- The `M` flag in class spell lists means a *specific* material component
  (one with a cost or that is consumed), not any material component.

### Stage 2 — the artifact validates the graph

Same idea one stage on: `meta.counts` is an independent statement of what
should be in the database. `verify.py` runs 67 checks — a count per label, a
count per `entity_type`, the creature↔section join at 336/336, one parent per
section outside the 16 roots, all 5255 reference edges present with zero
unresolved endpoints, 1314 abilities each attached to a creature, every
section still carrying its page and char offsets, and every section with
prose carrying a vector of the right width under an index that came online. A non-zero failure count
exits non-zero.

Two orphan groups are exempt, because they are facts about the book rather
than load failures, and are reported instead:

- The 3 front-matter roots (Legal Information, Contents, Index of Stat
  Blocks) have no subsections and nothing references them.
- 20 weapon and armour rows are printed only in a table. A Dagger has a
  price and a damage die but no prose section of its own and no creature
  carrying one.

## Known source-document quirks

These are errors or omissions in the SRD itself, not extraction failures.
They are reported, not silently corrected — except the first, where the
rules-correct value is used and the printed one kept in `printed_score`.

- **Gray Ooze** prints `Initiative −2 (13)`, implying Advantage on Initiative,
  but nothing in its stat block grants it. It lost *False Appearance* in the
  2024 revision; the score looks left behind. The pipeline uses 8 and warns.
- **Flaming Sphere** — its subtitle says Conjuration, all three class lists
  say Evocation.
- **Mind Spike** — subtitle claims Sorcerer, but it is on no Sorcerer list.
- **Phantasmal Force** — appears on no class list at all; the string occurs
  only twice in the entire PDF.
- **Young White Dragon** prints `Int 6 −2 2`, dropping the save's sign.
- **Create Undead** writes its material cost as `one 150+ GP black onyx
  stone`, not the usual `worth 150+ GP`.

## Not done yet

- Class spell-list edges are `references_spell` from a `class_feature`
  source; a proper `grants_spell` relation with class and level is the
  obvious next step. `ON_SPELL_LIST` (from each spell's own subtitle) is the
  closest thing in the graph today.
- The fusion weights both arms equally, which is reciprocal rank fusion's
  known weakness with an uninformative one. Asked "how much damage does a
  longsword do", the lexical arm has nothing and returns "One Thing at a
  Time" at rank 1, where RRF credits it exactly as it credits the dense arm's
  correct rank 1. A per-arm weight, or a floor on the Lucene score below
  which the arm is dropped, is the obvious next iteration; `found_by` is
  already there to measure it by.
- Nothing reranks. The fused top three is handed to the model as it comes,
  and a cross-encoder over the eight candidates is the standard next step.
- Spell mechanics are lighter than creature mechanics (spells use prose, not
  the stat block's labels): ability and damage yes, target shapes no.
- There are no typed traversals. `query_srd_graph` covers the long tail and
  `explore_srd_graph` covers exploration, but the two or three question
  shapes that actually recur (`creatures_imposing(condition)`) would be
  cheaper and more reliable as tools of their own than as Cypher the model
  composes each time.
- `fan` widens every group at once, so it is a blunt way to ask for one.
  The node budget now rises with it, which stops a wider ask returning less,
  but the right answer to "all of them" is `query_srd_graph`, and the walk's
  docstring says so rather than pretending otherwise.
- **An exhaustive question still fans out.** "Which creatures can make
  someone Frightened" is answered correctly, and in sixty-odd tool calls: the
  agent walks the graph, gets its list, and then verifies every creature on
  it with a search and a section read, plus a long tail of guesses at names
  the graph never mentioned. Neither the citability of the walk nor a wider
  fan moved that number. The graph gives the model a *list* and the model
  does not treat a list as an answer, which is a prompt problem and a tool
  problem at once: one typed traversal returning the creature, the ability
  and the save in a single result is what would end it.
- The graph explorer opens only on a citation. With nothing cited it says
  so rather than offering a way in — searching for a node to start from, the
  way the Page tab's page-number box is a way into the book, is the missing
  half.
- The panel shows the PDF, not the extracted markdown. `/source/{id}` still
  returns the text, and nothing renders it.
- No CI. Much of the backend suite needs nothing, and everything that wants
  the artifact, the vectors or a database skips cleanly without them. A
  workflow would want an `srd-parse` step, since the artifact is gitignored
  and the data-dependent tests skip without it, plus a
  `neo4j:5.26-community` service container for `tests/graph` and
  `tests/chat`; the frontend's `npm test` needs neither, and `e2e` needs
  Docker, the artifact and `srd_embeddings.idx`, since it starts its own
  database and the load now requires vectors. The `.idx` is the awkward
  one: it is gitignored, 13 MB, and generating it in CI would need a key on
  every run, so it wants caching by the artifact's digest or fetching from a
  release, which is the thing to decide before writing the workflow.
- An embedded graph for contributors without Docker was considered and
  parked. Kùzu is the obvious candidate but is not a drop-in: it is
  schema-first, a node belongs to exactly one node table, `SET n:Label` does
  not parse and undeclared properties are rejected. The model is multi-label
  throughout (`:Section:Spell`, `:Section:Rule:Equipment:Poison`), so Kùzu
  would need one table per type plus join relationships — a second loader
  building a differently shaped graph, which is precisely what an integration
  test should not be testing. Someone without Docker can still run the whole
  of stage 1 and everything but `test_loader.py`.
- One table is still misplaced relative to its heading (`Apparatus of the
  Crab Levers` neighbours on p210); the table itself is intact.
