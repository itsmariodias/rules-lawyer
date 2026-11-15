# rules-lawyer

Knowledge-graph RAG over the D&D 5e SRD (`SRD_CC_v5.2.1.pdf`, 364 pages).
The app is called Rules Lawyer: a chat that answers rules questions from the
SRD alone, cites the section behind every claim, shows the cited lines on the
printed page, and draws the graph around them.

Three stages, each meeting the next at one artifact:

1. **`srd/`**: PDF to `srd_hierarchy.json`, the book as data: a tree of
   sections holding typed blocks, entity records, and the edges between them.
2. **`graph/`**: that artifact (plus embeddings) into Neo4j.
3. **`chat/`**: questions answered from the graph, citing the book.

Nothing in `srd/` knows a database exists, nothing in `graph/` opens a PDF,
and nothing in `chat/` writes to either.

## Layout

A monorepo. `backend/` is the Python service, `frontend/` the React UI, `e2e/`
the Playwright suite; `data/`, `docker-compose.yml` and `.env` (from
`.env.example`) are shared at the root. Every `uv` command runs from
`backend/`; `config.py` resolves `data/` and `.env` from the repository root
regardless of the working directory. Each of `backend/`, `frontend/` and
`e2e/` has a README for people; this file is for agents.

```text
data/
  source/            the SRD PDF; checked in, never written
  output/            srd_hierarchy.{json,md,anchors.json}: reproducible
                     srd_embeddings.idx: reproducible only with an API key,
                     so also shared as a file (RULES_LAWYER_EMBEDDINGS)
  chat/              chat.sqlite (checkpoints), chat-store.sqlite (pins,
                     titles): not reproducible

backend/src/rules_lawyer/
  cli.py             rules-lawyer parse | embed | load
  config.py          pydantic-settings: RULES_LAWYER_*, NEO4J_*, CHAT_*, EMBED_*
  api.py             FastAPI app; assembles each package's router
  srd/               stage 1
    reading/         PDF to blocks, in reading order
      pages.py       spans grouped into lines by column and baseline; footers,
                     sidebar frames and table shading measured
      text.py        lines to styled runs: fonts to bold/italic, hyphenation
      tables.py      table lines to header, rows and cells by column
      statblock.py   stat blocks: name, fields, scores, sections of entries
      blocks.py      lines to headings, paragraphs, lists, contents, tables,
                     sidebars and stat blocks
    model.py         the block types (pydantic dataclasses) and Section
    sections.py      blocks to the section tree; floats placed
    entity_types.py  each section's type, from evidence
    vocabulary.py    closed vocabularies as StrEnums (conditions, damage
                     types, abilities, rarities, ...)
    entities/        records read from blocks: creatures, mechanics, spells,
                     equipment, characters (classes, species, backgrounds,
                     feats), glossary, annotate (fields on sections),
                     references (cross-reference edges), records (shared)
    output/          document (JSON in and out), render (the only code that
                     writes markdown), anchors (page rectangles)
    verify.py        the book checked against itself
    artifact.py      build, write and load the whole artifact
    routes.py        /health, /parse, /pdf
  graph/             stage 2
    model.py         NodeBatch / EdgeBatch: the mapper/loader seam
    mapping.py       document -> batches; pure, no driver or I/O
    embeddings.py    section texts, the .idx file format, generation policy
    schema.py        constraints, indexes, full-text and vector index, reset
    loader.py        batched UNWIND writes
    verify.py        post-load checks against the artifact
    pipeline.py      orchestration
    routes.py        /graph/health, /graph/load
  chat/              stage 3
    agent/           the model and everything built on it
      model.py       the chat model factory (Gemini) and NoApiKey
      build.py       LangGraph agent: system prompt, compiled and cached
      tools.py       the four agent tools
      titles.py      conversation titles
      prompts/       system.md, graph-orientation.md, title.md
    retrieval/       reads from the graph
      search.py      driver; lexical, dense and fused search; one section
                     by id; CITATION, the citation pattern
      cypher.py      guard, read-only transaction, derived schema, rendering
      neighbourhood.py  bounded walk around one node (graph view and tool)
      source.py      a citation -> markdown slice and page rectangles
    service.py       ChatService: ask, retry, history, lookups, pins, list,
                     delete; builds its model only to answer
    turn.py          one turn -> typed event stream
    threads.py       stored messages -> UI turns, traces and results (no I/O)
    routes.py        /chat, /chat/threads/*, /source/{id}, /neighbourhood

frontend/src/
  api.ts             client; ChatEvent mirrors turn.py's events
  useChat.ts         conversation state for the open thread
  useStored.ts       localStorage-backed state and theme
  useGraphStatus.ts  graph availability, polled until connected
  App.tsx            shell: thread list, conversation, side panel
  components/        Markdown, ToolTrace, Timing, Usage, SidePanel, PdfPage,
                     GraphView, graph-layout (pure layout maths), Resizer
  index.css          all styles; colour tokens at the top

e2e/                 Playwright over the whole stack (see Testing)
GRAPH.md             reference for every label and relationship type
.claude/skills/srd-extract/
                     the skill for work on srd/: block schema, audit and
                     PDF probe scripts
```

## Conventions

- **Tests:** one file per module, mirroring the package
  (`tests/graph/test_mapping.py` for `graph/mapping.py`; `api.test.ts` beside
  `api.ts`). Each test is a method on a class (or a `describe`) named for the
  function under test, written Given / When / Then with those comments.
  Unit tests need nothing; tests needing the artifact, vectors or an API key
  skip cleanly without them, and tests needing Neo4j carry
  `@pytest.mark.neo4j` and skip without Docker (see Testing).
- **Docstrings:** Google style, the summary on the opening `"""` line.
  Public functions document `Args`, `Returns`, `Raises` (and `Yields`)
  where they apply; private helpers get one line. Tool docstrings in
  `chat/agent/tools.py` are the exception (see below).
- **Comments** only for what the code cannot say: a library quirk, a bug
  being prevented, an SRD fact, a measured number. They describe the code
  and the book as they are, never the history of a change, a plan, or this
  file. Design rationale lives here.
- **Imports** are absolute from the top package (`from rules_lawyer.srd.model
  import Section`), never relative. An `__init__.py` with no code is empty:
  no docstring, no comment.
- **Constants for book facts** are named, with a comment giving the
  measurement behind them (`HEADING_LEVELS = {26.0: 1, ...}`), and come from
  something the book guarantees (a font, a size, a frame, a fixed phrase)
  rather than a statistical guess.
- **Tool docstrings in `chat/agent/tools.py` are prompt text.** LangChain parses
  them into the tool descriptions and `Args:` into the parameter schema, so
  edits change model behaviour.
- **Prompt files** in `chat/agent/prompts/` are sent verbatim: one paragraph per
  line, since a line break in the file reaches the model. Only the trailing
  newline is stripped. They are read at import, so a misspelt name fails at
  startup.
- **Commits** are conventional: `type(scope): subject`.
- **Docs that tests hold:** `tests/test_docs.py` fails if GRAPH.md falls
  behind `mapping`, if `KINDS` in `graph-layout.ts` misses a label, or if
  `Markdown.tsx`'s citation pattern differs from `search.CITATION`. When
  a count in this file changes (a re-parse, a load), update the tables here.

## Configuration

`config.py` reads `.env` and the environment.

- `Settings` holds the paths. `Settings.neo4j`, `.chat` and `.embedding` are
  `cached_property`s built on first access, so `parse` needs no
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
- `get_settings()` is cached; tests change the environment through the
  `settings_env` fixture, which clears it either side.

## Running it

```bash
docker compose up -d neo4j                     # NEO4J_PASSWORD from .env

cd backend
uv run rules-lawyer parse                      # data/output/srd_hierarchy.{json,md,anchors.json}
uv run rules-lawyer parse --pdf other.pdf --out /tmp/x.json
uv run rules-lawyer embed                      # srd_embeddings.idx; needs a key
uv run rules-lawyer embed --refresh            # re-embed everything
uv run rules-lawyer load                       # artifact + vectors -> graph, verify
uv run rules-lawyer load --no-reset --skip-verify
uv run rules-lawyer load --embeddings ~/Downloads/srd_embeddings.idx
uv run pytest                                  # -m "not neo4j" for the Docker-free set
uv run ruff check                              # lint (ruff's default rules); CI runs it
uv run uvicorn rules_lawyer.api:app --reload --reload-include '*.md'

cd ../frontend && npm install && npm run dev   # http://localhost:5173
npm test                                       # vitest
npm run coverage

cd ../e2e && npm install && npm run install-browsers && npm test
```

`parse` exits non-zero if the book disagrees with itself other than in its
known quirks; `load` exits non-zero if verification fails.
`--reload-include '*.md'` makes editing a prompt file restart the server.

The pipelines are importable: `srd.artifact.build`, `write` and `load`, and
`graph.pipeline.build_graph`. Progress goes through an injected `report`
callable (`graph.model.Report`; the CLI passes `print`). Every `__init__.py`
is empty, so importing one module pulls in only what it imports
(`graph.embeddings` loads no PDF reader, `chat.retrieval.cypher` no agent), and
importing a pipeline pulls in no web framework.

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

- The Neo4j driver is synchronous, so graph endpoints use `run_in_threadpool`,
  and async chat code (building the agent, resolving citations) runs its
  graph reads with `asyncio.to_thread`: on the event loop they stall every
  other stream.
- The API holds no state. `lifespan` opens one `AsyncSqliteSaver`
  (checkpoints) and one `AsyncSqliteStore` (pins and titles); routes reach
  them through `request.app.state`.
- Each package owns its `routes.py`; `/pdf` lives with stage 1 because it
  serves stage 1's input.

## Stage 1: the artifact

**Use the `srd-extract` skill for any work in `srd/`.** It carries the block
schema and two scripts: `audit.py` counts the defects a reader would notice
in an artifact, and `probe.py` prints what the PDF says about a page
(baseline, x, size and font per span). Settle every question about the book
with `probe.py` before writing a rule.

### The JSON is the book

`data/output/srd_hierarchy.json` holds `meta` (title, pdf, pages, generated,
markdown, counts), `sections` (a tree), seven flat collections and
`validation`. Each section has `id` (dotted, positional), `heading`, `level`,
`entity_type`, `blocks`, `subsections` and `source` (pages and character
offsets), plus optional typed fields (`spell`, `item`, `term`/`term_type`,
`members`).

- **Blocks** (`model.py`): `heading`, `paragraph` (with an optional bold
  `lead` and a `role` such as `subtitle`), `list` (items hold blocks),
  `table` (caption, header rows, rows of cells with `span`, notes, and
  `under` for category rows), `sidebar` (title and blocks), `contents` (the
  book's Contents and Index of Stat Blocks, kept as verification data) and
  `statblock` (name, subtitle, fields, ability scores, sections of entries).
  Every block keeps `pages`. Inline text is runs: a plain string, or
  `{"text", "bold", "italic"}`; run text is literal, never markdown.
- **The markdown is rendered from the JSON** by `output/render.py`, and
  nothing else writes it. `write` re-reads the JSON it wrote and refuses if
  that renders other markdown than the offsets were taken from. Every
  section's `char_start`/`char_end` is the renderer's span for it and covers
  its subtree. No page markers: pages live on blocks.
- **`load` adds `content`** to every section, rendered from its own blocks,
  so the graph, search and embeddings read exactly what the markdown shows.
- **`srd_hierarchy.anchors.json`** maps rendered character ranges to page
  rectangles. Geometry is build-time only (`Printed.boxes`), never in the
  JSON or the graph.
- Pydantic dataclasses with a discriminated union on `type`
  (`BLOCKS = TypeAdapter(list[Block])`) are the JSON round trip; optional
  fields are omitted when unset.

| Collection | Count | Notes |
| --- | --- | --- |
| sections | 2395 | tree, 16 roots; every node has an `entity_type` |
| creatures | 336 | stat blocks; 1336 entries (traits, actions, ...) |
| equipment | 146 | 38 weapons, 13 armour, 81 gear, 14 poisons |
| classes | 12 | core traits, 20-level progression, features, subclasses |
| species / backgrounds / feats | 9 / 4 / 17 | |
| glossary | 172 | 155 terms (15 conditions, 12 actions, ...), 13 damage types, 4 poison types |
| references | 5659 | typed edges between all of the above |

| `entity_type` | Count |
| --- | --- |
| `rule` | 688 |
| `spell` / `magic_item` (with a `spell` / `item` field) | 339 / 258 |
| `creature` (its stat block) / `creature_group` (`members`) | 336 / 177 |
| `class` / `subclass` / `class_feature` (232 features, 38 options) | 12 / 12 / 270 |
| `equipment` (81 gear items, 14 poisons) | 95 |
| `glossary_term` (`term`, `term_type`) | 155 |
| `origin` / `feat` / `front_matter` | 13 / 17 / 3 |
| `environmental_effect` / `trap` / `contagion` | 9 / 8 / 3 |

References by relation: `references_spell` 2172, `references_damage_type`
1655, `references_condition` 538, `references_area_of_effect` 354,
`references_action` 306, `imposes_condition` 303, `references_table` 162,
`references_creature` 101, `references_magic_item` 68.

### How the book is read

Each module knows only the one before it: lines know nothing of blocks,
blocks nothing of sections, sections nothing of entities, and the renderer
reads only sections. A wrong markdown line is fixed in the stage that built
the block, never by post-processing text.

- **Lines, by baseline.** PyMuPDF's block order sometimes sorts a
  bottom-of-column fragment after the facing column, so spans are grouped
  into lines by **baseline** (bbox tops are inflated by font metrics). The
  footer is split off (its title, which every page must agree on, is the
  document's `title`). A raised superscript joins the span before it.
- **Columns are measured per page** from line starts: an edge shared by at
  least 3 prose lines with a clear strip to its left. Table spans and notes
  are left out of the test, since a table may run the page's width. A table
  shaded in two blocks side by side gives the second edge (Trinkets, page
  27); a table shaded across the gutter spans both columns.
- **Paragraphs cross breaks.** Blocks are read from the whole book at once,
  so a paragraph continues across a column or page break unless the next
  line shows it starts one: an indent, extra leading, a bold lead, a list
  marker, or the previous line ending a sentence where the next word would
  have fitted. A bold first word starts a hanging paragraph.
- **Typography carries structure.** `GillSans-SemiBold` (and its small-caps
  face) at 26/18/14/12/10.5pt is H1 to H5; a level 5 heading directly above
  a table is its caption. Spans more than 1pt apart with no space between are
  a word apart (small-caps sidebar titles extract with no spaces).
- **Hyphenation.** A line-end hyphen is kept only if the book prints that
  hyphenated word mid-line ("foot-wide"), or before a capital
  ("Three-Quarters"); soft hyphens are dropped; a zero-width space after a
  hyphen keeps it. A line break at a dash adds no space.
- **Tables:** header `GillSans-SemiBold` 9.2, cells `GillSans` 9.5 (italic
  and bold cells too). Rows step about 15pt and wrapped cells 12.5, so a
  line less than 14pt below the last continues its row, on the same
  shading. A cell goes under the one header label it overlaps; an upper
  header label ("Spell Slots per Spell Level") goes over the first label it
  overlaps. Repeated header labels mean one table printed in side-by-side
  halves, stacked left first. A category row (italic first cell, the rest
  empty) heads the rows indented under it (`under`; the markdown marks them
  "↳ ").
- **Sidebars** are sidebar-grey frames with a dark shadow; a grey band
  without a shadow is a table row.
- **Stat blocks are their own block type,** identified by type: a
  `GillSans-SemiBold` 14.8pt title, then lines in Optima (used only in stat
  blocks) or the stat block GillSans sizes. Each field (`Optima-Bold` 9)
  starts a paragraph; the scores are a table of Ability, Score, MOD, SAVE;
  section headers ("Actions") are plain GillSans 12; entry names are bold
  italic, and later paragraphs continue the entry.
- **Floats.** Tables, sidebars and stat blocks never interrupt running text:
  met mid-paragraph or in an open list, they follow it. In the tree a float
  is a section of its own, one level below where it is printed.
  `place_floats` moves a captioned table to the shallowest section naming it
  in a paragraph ("the Barbarian Features table"; a list's mention is not
  ownership), within its level 2 section, at the end nearest where it was
  printed; a sidebar the Contents lists goes after its listed sibling
  ("Running a Monster"); every other float stays where printed.
- **A section is `rule` unless evidence types it** (`entity_types.py`):
  `spell` and `magic_item` only from the italic subtitle under the heading,
  `creature` from a stat block, `creature_group` only in the monster
  chapters (an entry over stat blocks), `glossary_term` from Rules
  Definitions, closed sets (traps, environmental effects, contagions,
  Metamagic and Eldritch Invocation options), front matter on pages 1 to 4;
  then from records (`type_from_records`): classes, subclasses, features,
  species, backgrounds, feats, gear, poisons. A chapter's position types
  nothing: "Classes" once made 446 sections class features. Elsewhere a
  printed stat block (a summoned creature, a figurine) is a `creature` and
  the spell or item around it keeps its type.
- **Records are read from blocks and runs,** never from markdown. Stat block
  labels are italic runs ending in a colon. Immunities are sorted by name
  against the `Condition` vocabulary, not by the semicolon: a line of
  conditions alone has none. A qualified entry keeps its note ("Charmed
  (with _Mind Blank_)") and so links to nothing. Gear and poisons record
  `section_id` so stage 2 folds them into their section; weapons and armour
  record `table_id`, and a class `features_table_id`, the table each is
  read from.
- **Cross-reference edges come from runs** (`entities/references.py`):
  italic runs resolve to spells, then magic items; bold runs to creatures,
  plurals included; a run becomes an edge only if it names an extracted
  entity (italics also mark emphasis and book titles). Conditions, actions,
  damage types and areas match fixed phrasing built from the vocabulary
  (`Prone condition`, `a 20-foot Cone`) so `Cover`, `Attack` and `Force`
  never fire as bare nouns; name lists ("the Deafened and Frightened
  conditions") count every name. A captioned table is named by its caption,
  capitalised, before "table" ("the Barbarian Features table"); a table
  never references itself. Sources are each section's own blocks (table
  cells included) and each creature entry, with `part` (`actions/Bite`).
- **`imposes_condition` vs `references_condition`.** Only
  `mechanics.conditions_imposed` decides "imposes": "has the X condition" (X
  may be an *and* list), skipped when a negating word appears in the same
  clause. *Or* lists are not imposed: "the Grappled, Incapacitated, or
  Restrained condition" is usually target eligibility.
- **Page anchors:** one box per line from baseline and size
  (`baseline - 0.80*size` to `baseline + 0.24*size`), since PyMuPDF reports
  most lines on a page as 56pt tall; horizontal extent is reliable. 8145
  anchor parts; every section has boxes, all on its own pages.

### The book checks itself

`verify.py` holds every place the book says one thing twice; `parse` fails
on any disagreement not in `KNOWN` (the source quirks below).

- **Contents:** each of its 150 entries is a heading or sidebar title on its
  page, in order, under its Contents parent.
- **Index of Stat Blocks:** 330/330 name a stat block on their page. The 6
  not indexed are printed in spells and items.
- **Spells:** every class spell list row against each spell's subtitle (339
  spells; level, school and classes both ways).
- **Classes:** each features table against its "Level N: Name" headings.
- **Gear:** the Adventuring Gear table against the "Name (price)" headings.
- **Weapons:** every property and mastery of the 38 weapons is defined.
- **Creatures:** damage averages against their dice (715, 0 mismatches),
  attack bonuses as ability modifier plus proficiency bonus (414, 0), ability
  modifiers, HP formulas, Initiative scores and passive Perception per stat
  block (warnings in `validation.stat_block_warnings`).
- **References:** zero unresolved targets. **Anchors:** none misplaced.

Rules that cost debugging time:

- A passive score is `10 + bonus`, **plus or minus 5 for Advantage or
  Disadvantage.** The Invisible Stalker's `+7 (22)` is correct: it is
  permanently Invisible, which grants Advantage on Initiative.
- The `M` flag on class spell lists means a *specific* material component
  (with a cost or consumed), not any material component.

### Known source-document quirks

Reported, not corrected, except the first, where the rules-correct value is
used and the printed one kept in `printed_score`.

- **Gray Ooze** prints `Initiative −2 (13)`, implying Advantage nothing
  grants. Uses 8 and warns.
- **Flaming Sphere:** subtitle says Conjuration, all three class lists say
  Evocation.
- **Mind Spike:** subtitle claims Sorcerer; it is on no Sorcerer list.
- **Phantasmal Force:** subtitle names Bard, Sorcerer and Wizard; it is on
  none of their lists.
- **Young White Dragon** prints `Int 6 −2 2`, dropping the save's sign.
- **Create Undead** writes `one 150+ GP black onyx stone`, not `worth 150+ GP`.
- **D20 Test** steps on page 6 are numbered 4 to 6, continuing page 5's
  list; kept as printed (`start: 4`).
- **Cure Wounds** in the Life Domain spells (page 40) has its final "s" set
  upright, the only style change inside a word in the book.

## Stage 2: the graph

`rules-lawyer load` writes **3900 nodes and 12025 relationships**, then runs
**79 verification checks**. Loads MERGE on stable keys, but a full reset is
the default: the artifact is the whole truth, and merging alone would keep
nodes a re-parse has dropped.

| Label | Key | Count |
| --- | --- | --- |
| `:Section` | `id` | 2256 (2395 less 139 wrappers) |
| + `:Spell` / `:MagicItem` / `:Creature` / `:Rule` / `:ClassFeature` / ... | `id` | 339 / 258 / 336 / 688 / 270 / ... |
| + `:Class` / `:Subclass` / `:Feat` / `:Origin` (+ `:Species` / `:Background`) | `id` | 12 / 12 / 17 / 13 (9 / 4) |
| + `:CreatureGroup` | `id` | 38 |
| + `:Trap` / `:EnvironmentalEffect` / `:Contagion` | `id` | 8 / 9 / 3 |
| + `:GlossaryTerm` + `:Condition` / `:Definition` / `:Action` / ... | `id` | 155 |
| + `:Equipment` + `:Gear` / `:Poison` | `id` | 81 / 14 |
| `:GlossaryTerm` + `:DamageType` / `:PoisonType`, sharing a passage | `name` | 13 / 4 |
| `:Equipment` + `:Weapon` / `:Armor` | `name` | 51 table rows |
| `:CreatureAbility` | `key` (`Goblin\|actions/Bite`) | 1336 |
| `:ClassLevel` | `key` | 240 |

Relationships: the artifact's reference relations uppercased
(`IMPOSES_CONDITION`, `REFERENCES_SPELL`, `REFERENCES_TABLE`, ...); structure (`HAS_SUBSECTION`,
`HAS_ABILITY`, `HAS_FEATURE`, `HAS_SUBCLASS`, `AT_LEVEL`, `GRANTS_FEATURE`,
`DEFINED_IN`); and edges derived from list fields
(`IMMUNE_TO`, `RESISTANT_TO`, `VULNERABLE_TO`, `IMMUNE_TO_CONDITION`,
`ON_SPELL_LIST`, `CARRIES`, `HAS_POISON_TYPE`, `GRANTS_FEAT`). GRAPH.md
documents each one.

### Graph decisions

- **The section tree is the spine; entity types are extra labels.** A spell
  *is* its section, so everything a traversal finds keeps
  `char_start`/`char_end` and resolves to the book. The dotted section id is
  the only globally unique stable identifier, so it is the key.
- **An entity printed under its own heading folds into that section:**
  creatures, gear, poisons, classes, subclasses, species, backgrounds, feats
  and glossary terms. Side by side they were 1:1 copies joined by
  `DEFINED_IN`, each a hop between a question and its citation.
  `add_creatures` and `Mapper.fold` raise if a record names no section of
  its type. The section label is the record's (`:Section:Class`), and edges
  still match `(:Class {name})`, so name constraints stay. Weapons and
  armour are only table rows, so they stay `:Equipment` nodes `DEFINED_IN`
  their table; the 13 damage types share `11.2.46.1` and the 4 poison types
  `12.6`, so those 17 terms stay nodes `DEFINED_IN` it.
- **Floats are sections, reached three ways.** A captioned table, sidebar or
  stat block hangs from its owner by `HAS_SUBSECTION`. A table is also
  reached by `REFERENCES_TABLE` from every section naming it (97 of the 193
  are named), and by `DEFINED_IN` from the rows that are nodes: each class's
  20 `:ClassLevel`s and the 51 weapons and armour, so a row cites the table
  printing it. Before these, most tables were leaves reachable only through
  their parent, and 20 weapons and armour were orphans.
- **Species and feat traits are a `traits` name list,** not nodes: nothing
  refers to any of the 61, and their text is in the section.
- **A monster entry wrapping its namesake is left out** (`is_wrapper`: no
  prose, one subsection, a stat block of the same heading; 139). Its stat
  block hangs from the entry's parent and keeps its id, so the artifact,
  embeddings and stored citations are untouched. The 7 entries over a stat
  block of another name stay ("Crawling Claw" over "Swarm of Crawling
  Claws"): the heading is the only place that name is printed.
- **Creature entries are nodes because references point at them.** A
  creature-sourced reference's `part` (`actions/Bite`) is the tail of the
  ability key, so 1619 edges land on the ability rather than the whole stat
  block.
- **Targets are matched, never merged.** An unresolved target is reported in
  `unresolved`, not created as an empty node. All 5659 currently resolve.
- **Poison types are nodes** because nothing refers to them; without
  `HAS_POISON_TYPE` the paragraph defining "Injury" is unreachable.
- **`mapping.py` is pure.** No driver; `loader.py` only batches and writes.
- **Nested values fail at map time.** Neo4j stores primitives and homogeneous
  arrays; `clean()` raises naming the field (Neo4j names only the value).
  Damage lists become parallel `damage_dice` / `damage_types` /
  `damage_averages`; `resources` becomes `resource_names` / `resource_values`.
- **Uniqueness constraints double as the MERGE indexes.**

### Embeddings

- One vector per section with prose (2173; `EMBED_DIMENSIONS`, default 1536,
  truncated from 3072 and normalised by us, since the API only normalises at
  full width). The text is the section's `content` prefixed with its heading
  path (`Monsters > Goblin > Actions`), because dozens of sections are
  called "Actions".
- **Required.** A load with neither a complete `.idx` nor a key raises
  `MissingEmbeddings` before opening a session, leaving the previous graph
  standing. The message names both ways out.
- **`.idx` format:** magic `DNDEMB\0`, a uint32 header length, a JSON header
  (model, dimensions, task type, keys, per-section text digests), then raw
  little-endian float32. Standard library only (`array`), no numpy or FAISS.
- **The header makes it a cache.** Digests mean a re-parse re-embeds only the
  changed sections, matched by digest under any id, since ids are positional
  and one new section renumbers its later siblings. A file made under
  another model, width or task type is discarded whole: two vector spaces in
  one index rank nonsense silently. Truncation (`EMBED_MAX_CHARS`) happens
  before the digest. Re-embedding costs API calls.
- Vectors are written in their own pass (`EMBEDDING_QUERY`), so `mapping`
  stays pure and `clean()` never walks 1536 floats per row.
- **`apply_schema` drops `srd_vector` if its width differs** from the vectors
  being written; `CREATE ... IF NOT EXISTS` would keep the old index, which
  indexes nothing of the new width.

### Verification (`verify.py`)

Expected values come from the document (`meta.counts`, collections), never
from the loader's tally; the one rule shared with the mapper is
`wrapper_groups`, subtracted from the section and `creature_group` counts.
Checks: a count per exact label set and per `entity_type`; collections;
records folded (none of `:Class` ... `:Feat` outside a section); 17 terms
`DEFINED_IN` a shared passage; no wrapper left and `members` on every
group; 240 class levels and 51 weapon and armour rows `DEFINED_IN` their
table; 336 creatures
with stats; 16 roots and one parent per section; all 5659 reference edges
and zero unresolved; 1336 abilities, each attached;
abilities with damage; sections with prose each having a vector of the right
width; `srd_vector` online and of that width; no orphans but the 3
front-matter roots, which nothing in the book refers to. Non-zero failures
exit non-zero.

## Stage 3: the chat

A LangGraph tool-calling agent (`langchain.agents.create_agent`) on Gemini
(`CHAT_MODEL`, pinned) with four tools:

| Tool | Does |
| --- | --- |
| `search_srd` | hybrid search; `CHAT_SEARCH_LIMIT` candidates per arm, fused to `CHAT_TOP_K` |
| `get_srd_section` | one section by dotted id, with parent and children |
| `explore_srd_graph` | the bounded walk around a section, as prose |
| `query_srd_graph` | read-only Cypher |

`ChatService` (`service.py`) is what the routes call: `ask`, `retry`,
`history`, `lookup`, `list_threads`, `set_pinned`, `forget`, over the
checkpointer and the store. Its `model` is a `cached_property`: only `ask`
and `retry` read it, so stored conversations open without a key.
`turn.stream_turn` flattens LangGraph's stream into events: `start`,
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
- A dense index always has a nearest neighbour, so search does not say
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
  failing the turn. `build_agent` compiles the agent every turn, prompt
  included (about 2ms; building the Gemini client costs 16), so the schema
  is picked up once the graph is reachable.

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
  ability cites the stat block printing it (`HAS_ABILITY`); a damage type,
  poison type, class level, weapon or armour its `DEFINED_IN` section;
  anything printed nowhere says "do not cite". Without this the model searched for each node by name.
- A condition is its section, so one hop from it reaches what imposes it.
  A damage type is one hop past its shared passage, so the docstring tells
  the model to walk depth 2 when depth 1 shows only `DEFINED_IN`.
- Nodes are addressed by `elementId` (stable for the life of a load), since
  derived nodes have no section id.

### Answers, failures and citations

- **The tools are the only source of truth,** and the system prompt says
  the model's own D&D knowledge must not decide what to check either. Of 20
  calls on the Frightened question, about 8 tested recollections of older
  editions (every adult dragon with Frightful Presence, a frightening
  Phantasmal Killer) against a graph that was right; answering from the
  tools alone was not enough to stop that.
- **The model is required, and a failure is the reply.** No fallback answer.
  A missing key is knowable before the stream starts: `ask` and `retry`
  build the model before returning their stream, so `/chat` and retry
  answer 503; everything else arrives as an `error` event. `_explain` names the common
  failures (no key, rejected key, spent quota) and truncates the rest.
- **A stall is not an error by itself,** so `_until_silent` fails a turn
  after `CHAT_TIMEOUT_SECONDS` of silence, reset by every token and tool
  result.
- **The model is never switched by configuration:** `ChatService.model`
  builds the configured one (`agent.model.model()`), lazily. Tests replace
  the `chat_service` route dependency through `app.dependency_overrides`
  with `fake_chat_service`, whose `FakeChatService` overrides `model` with
  `FakeChatModel` (`tests/fakes.py`). The fake calls the real `search_srd`
  and cites the first result; asked for a title it replies with a search,
  so conversations stay untitled. e2e serves `tests/e2e_app.py`, the app with that override, so
  no production code knows a fake exists.
- **Citations come from the answer.** The prompt asks for `[11.2.114]` after
  each claim; `resolve_citations` resolves the ids in the finished text, in
  order of first appearance, dropping invented ones. The pattern is
  `search.CITATION`; `Markdown.tsx` has a copy that `test_docs.py` holds
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
  without counts shows nothing. The fake reports a fixed 1230 per call.

### Threads

- History lives in the checkpointer, keyed by a thread id the browser holds.
  There is no thread table: deleting the checkpoints is deleting the thread.
- **Stored threads are read from the checkpointer, not the agent,** since
  building the agent needs a model and so a key: a stored conversation opens
  without one. Tool results a running step has already written are read
  from its pending writes, as `aget_state` reads them.
- **The list scans the newest checkpoints** (40 per thread listed; a turn of
  20 lookups writes over 40), so old threads drop off it. Pinned threads are
  fetched by id and always listed, beyond the limit too.
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
  one checkpoint, so `ChatService.retry` finds the newest checkpoint without
  the last question and the retry branches from it; later checkpoints stay on disk,
  unreachable. The question is read from the checkpoint, not resent. The
  graph checkpoints before the input, so the first turn also has a state to
  branch from. An empty thread is a 404 before the stream starts.
- **Reopened conversations keep their trace:** `turns_of` (pure) attaches
  tool calls to the answer that follows them; a failed turn's calls do not
  leak into the next. `name_missing_subjects` fills `subject` for threads
  stored before tools returned artifacts.
- **Tool results are fetched on demand** (`/lookups/{call_id}`): one turn of
  the Frightened question stored 20 results and about 100 KB. Each result
  is stored as its tool finishes, so this works mid-turn.
- **Turns are dated from the checkpoint** (`written_at`: the earliest
  checkpoint containing each message). Durations are measured in the browser,
  from send to stream end.

## Frontend

React 19, TypeScript and Vite; `react-markdown` with `remark-gfm`, and
`pdfjs-dist`. No state library, router, CSS framework or graph library. Vite
proxies `/api/*` to the backend (`VITE_API_TARGET`, default `:8000`), so the
browser stays on one origin and the SSE stream shares it.

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
  panel area per node. Positions live in a ref, not React state, so the
  simulation moves them every frame.
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
- **Filled nodes are sections; hollow nodes are derived,** so a reader can
  tell what opens on the page.
- Edge types are labelled only on the selected node's edges, at most five.

## Testing

- `uv run pytest`: backend. Tests needing Neo4j share one
  Testcontainers `neo4j:5.26-community` container per run (the `neo4j`
  fixture), loaded once from the artifact and its vectors (`graph`), its
  memory capped as e2e's is (512 MB heap, 256 MB page cache).
  `pytest_configure` points `NEO4J_URI` at a closed port first, so a test
  that forgets the fixture fails rather than writing to the `.env`
  database. Those tests carry `@pytest.mark.neo4j` (on the class when every
  method needs it), and collection fails if the mark and the fixture
  disagree, so `-m "not neo4j"` is exactly the Docker-free set.
  Markers are strict.
- A new database test asks for `graph` (a session on the loaded container),
  or `graph_session` if it loads what it needs itself, and is marked.
- `npm test` in `frontend/`: vitest and Testing Library in jsdom, no
  backend; `fetch`, pdf.js and the graph view are mocked where needed.
- `npm test` in `e2e/`: Playwright over Vite, FastAPI and a **fresh Neo4j
  container** loaded from this checkout's artifact (not the docker-compose
  database). Own ports (8001, 5174, 7688) and own `.data` directory, with
  `chat/` emptied each run. Served by `tests.e2e_app` (the fake model) with
  a blank `GOOGLE_API_KEY`, so no quota is spent and search is lexical only.
  Needs Docker, the artifact and `srd_embeddings.idx`; skips without them. Specs import `test` from
  `fixtures.ts` and use its `app` fixture, which is what skips them. The
  development Neo4j can stay up: `docker-compose.yml` caps its memory as the
  test containers are capped. Short of memory, macOS suspends the browser's
  network service and streamed turns fail, so global setup notes a database
  on 7687; one retry covers it.
