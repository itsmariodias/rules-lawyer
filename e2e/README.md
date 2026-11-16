# End-to-end tests

Playwright driving a real browser against the whole stack: Vite, FastAPI,
Neo4j and the generated SRD files. The [backend](../backend/README.md)'s
pytest checks modules and the [frontend](../frontend/README.md)'s vitest
checks components with `fetch` mocked; this suite checks what a reader
actually does: ask, follow a citation, walk the graph, come back to a
conversation.

## Commands

```bash
npm install
npm run install-browsers      # once: Playwright's Chromium
npm test                      # the whole suite; starts and stops everything
npm run test:headed           # the same, with a browser window to watch
npm run report                # the HTML report of the last run
npm run typecheck
npx playwright test specs/graph.spec.ts   # one file
```

Nothing needs to be running first. You do need:

- **Docker**, for the database;
- **the parsed SRD** (`cd ../backend && uv run rules-lawyer parse`);
- **the embeddings** (`uv run rules-lawyer embed`, or a shared
  `srd_embeddings.idx` in `data/output/`).

Without any of them the run prints why and skips, rather than failing.

## What it runs against

Everything is separate from a development session, so the two never
interfere:

| | |
| --- | --- |
| **API** | `uvicorn` on port **8001** |
| **App** | `vite` on port **5174**, proxying `/api` to 8001 |
| **Database** | a fresh `neo4j:5.26-community` container on **7688**, loaded from the generated JSON each run |
| **Data** | `.data/`: `source/` and `output/` link to the real ones, `chat/` starts empty |

A fresh database means a passing run tests the whole chain (parse, load,
search, answer, cite) rather than whatever happens to be in your local graph.

**No API key, no model.** The API is served by `backend/tests/e2e_app.py`,
which builds the app with a fake chat model (`backend/tests/fakes.py`) in
place of a real one. It
calls the real `search_srd` tool against the real graph and cites the first
result, so every event a real turn sends still crosses the wire; only the
answer's wording is canned. With no key, search is full-text only.

## Layout

```text
playwright.config.ts   the two servers, their ports and environment
ports.ts               ports, the Neo4j image and password
stack.ts               starts the Neo4j container and loads the graph
global-setup.ts        runs stack.ts once; decides whether to skip
prepare-data.mjs       builds .data/ before the API opens it
fixtures.ts            the `test` every spec imports, plus helpers
                       such as `ask(page, question)` and `panel(page)`

specs/
  chat.spec.ts         ask, stream, tool trace, citations, open a citation
  side-panel.spec.ts   the PDF page, its highlight boxes, the whole book, widths
  graph.spec.ts        the graph view: selection, expansion, depth
  threads.spec.ts      listed, reopened after a reload, pinned, deleted
```

To add a test, import `test` and `expect` from `../fixtures` rather than
from Playwright, and use its `app` fixture (the page, already loaded) instead
of `page`. That fixture is what skips the test when the stack is unavailable,
and it attaches the browser's console errors to a failure.
