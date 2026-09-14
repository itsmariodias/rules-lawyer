# End-to-end tests

A real browser against the real stack: Vite, FastAPI, Neo4j and the artifact
on disk. Where `frontend`'s vitest suite mocks `fetch` and asserts on
components, and `backend`'s pytest suite asserts on modules, this drives the
flows a reader actually performs — ask, cite, open the page, walk the graph,
keep the conversation.

```bash
npm install
npm run install-browsers      # once: Playwright's Chromium
npm test                      # the whole suite, servers and all
npm run test:headed           # the same, with a window to watch
npm run report                # the HTML report of the last run
```

Nothing else needs to be running: `npm test` starts everything it needs and
takes it all down afterwards. It needs Docker for the database, and an
artifact — `cd backend && uv run srd-parse` — and skips with a line saying so
if either is missing, rather than failing.

## What it runs against

| | |
| --- | --- |
| **API** | `uvicorn` on **8001**, `CHAT_STUB=1` |
| **App** | `vite` on **5174**, proxying `/api` to 8001 |
| **Database** | a `neo4j:5.26-community` container on **7688**, loaded from the artifact |
| **Data** | `.data/`, where `source/` and `output/` link to the real ones and `chat/` starts empty |

Three deliberate separations, each of which was a bug before it was a rule:

**Its own ports.** 8001 and 5174, never 8000 and 5173, so a dev session is
neither disturbed by a run nor mistaken for the server under test.

**Its own database.** Not the Neo4j from `docker-compose.yml`, which holds
whatever the last `srd-graph-load` put in it — that would make a passing run
mean "the graph on this machine happens to be right". A container filled from
the artifact each run tests the whole chain instead: parse → load → retrieve
→ answer → cite. Its port is *bound* rather than assigned, because Playwright
starts the servers before global setup: the API has to be told where the
database will be before the container exists, and it opens no connection
until the first query, which is a test away.

**Its own data directory,** built by `prepare-data.mjs` from the API's own
command line — not by the config, which Playwright loads again in every
worker, and not by global setup, which runs after the servers are up. Either
of those empties `chat/` under a server already holding `chat.sqlite` open,
and every write then fails with a disk I/O error partway through a turn.

## Why the model is never called

`CHAT_STUB=1` runs the scripted model in `chat/stub.py`: it calls the real
`search_srd` against the real graph and cites what comes back. No API key, no
quota, no non-determinism — and every event a live turn emits still crosses
the wire, because the agent loop, the tools and the citations are the live
ones. What it costs is the model's prose, which is the one part of the answer
no assertion could pin down anyway.

It is a test seam, not a fallback: nothing turns it on in response to a
failure, and a real turn that cannot reach the model fails.

## Give it the memory

Stop the development database first:

```bash
docker compose stop neo4j     # from the repository root
```

This suite brings its own, so that one is only in the way — and two Neo4j
JVMs is more than a laptop has to spare. What gives way under the pressure is
not the database but the browser: macOS suspends its network service, which
kills whichever streamed turn was open and fails the test waiting on it, with

```
request failed: http://localhost:5174/api/chat (net::ERR_NETWORK_IO_SUSPENDED)
```

Measured over five runs: four to six failures of thirty-three with the
development instance up, none at all with it stopped, and half the wall-clock
time — 2.7 minutes against 7. Global setup warns when it finds something on
7687, and `retries: 1` covers a machine that is busy for some other reason.

Two things this is *not*, both tested rather than assumed: it is not idle
sleep (`caffeinate -i` made no difference) and it is not the test database's
own heap (capping it made no difference, though the cap was kept).

## Layout

```text
playwright.config.ts   the two servers, the ports, the reporters
ports.ts               where the stack listens; imported by the config, which
                       must stay light enough not to trip Node's CJS interop
stack.ts               the Neo4j container, and the load that fills it
global-setup.ts        start it, fill it, decide whether to skip
prepare-data.mjs       the data directory, built before the server opens it
fixtures.ts            the `test` every spec imports, plus `ask`
specs/
  chat.spec.ts         ask, stream, trace, cite, open the citation
  side-panel.spec.ts   the page facsimile, its boxes, the book, the widths
  graph.spec.ts        the neighbourhood, selection, expansion, depth
  threads.spec.ts      listed, reopened after a reload, pinned, deleted
```
