/**
 * The end-to-end run: a real browser, the real API, the real graph.
 *
 * Where the vitest suite mocks `fetch` and asserts on components, this drives
 * the whole stack — Vite, FastAPI, Neo4j and the artifact on disk — through
 * the flows a reader actually performs. Both servers are started here, so
 * `npx playwright test` is the only command.
 *
 * Three things keep it out of the way of a working checkout:
 *
 * * its own ports (8001 and 5174), so a dev session on 8000/5173 is neither
 *   disturbed nor mistaken for the server under test;
 * * its own data directory, `.data`, whose `source/` and `output/` link
 *   through to the real artifact while `chat/` is emptied before every run —
 *   so the conversations these tests create are never the reader's;
 * * its own database, a container started and filled from the artifact by
 *   global setup, so a passing run means the artifact in this checkout
 *   produces a graph the UI can answer from — not that the graph on this
 *   machine happens to be right (see `stack.ts`).
 *
 * `CHAT_STUB=1` runs the scripted model in `chat/stub.py` instead of Gemini:
 * no API key, no quota, no non-determinism. The agent loop, the tools, the
 * graph and the citations are all the real ones — only the sentences are
 * fake, and they are the one part of an answer no assertion could pin down
 * anyway.
 */

import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

import { API_PORT, APP_PORT, NEO4J_PASSWORD, NEO4J_URI } from './ports'

const here = __dirname
const root = path.resolve(here, '..')
const backend = path.join(root, 'backend')
const frontend = path.join(root, 'frontend')
// Named here, built by the API's own command line: this config is loaded
// once per worker as well as in the main process, so nothing in it may
// touch the filesystem.
const data = path.join(here, '.data')
const prepare = path.join(here, 'prepare-data.mjs')

export default defineConfig({
  testDir: './specs',
  globalSetup: './global-setup.ts',
  // The stack is shared and stateful — one SQLite file, one graph — so the
  // specs run in file order rather than racing each other through it.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // Starting a database and loading 4260 nodes into it is a minute or two
  // before the first assertion.
  globalTimeout: 20 * 60_000,
  // One retry everywhere, not only in CI, as a net under
  // `net::ERR_NETWORK_IO_SUSPENDED` — the browser's network service being
  // suspended under memory pressure, which kills whichever streamed turn
  // was open. Global setup says what usually causes it; the retry is for
  // when the machine is busy for some other reason.
  retries: 1,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    // `localhost`, not `127.0.0.1`: Vite binds the loopback name, which
    // resolves to ::1 here, and the two are not the same address.
    baseURL: `http://localhost:${APP_PORT}`,
    // Kept only for a failure: a passing run leaves nothing behind.
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          // A turn is a stream held open for seconds. Chrome throttles both
          // timers and rendering in a window it believes nobody is looking
          // at, which is every window in a headless run.
          args: ['--disable-background-timer-throttling',
                 '--disable-backgrounding-occluded-windows',
                 '--disable-renderer-backgrounding'],
        },
      },
    },
  ],
  webServer: [
    {
      // The data directory is built by the same command that opens it, so
      // it cannot be emptied out from under a running server.
      command: `node "${prepare}" `
               + `&& uv run uvicorn dnd_graph_rag.api:app --port ${API_PORT}`,
      cwd: backend,
      // `/health` needs neither the database nor a key, so it answers as
      // soon as the app is up; whether the graph is loaded is global-setup's
      // question.
      url: `http://127.0.0.1:${API_PORT}/health`,
      // Pointed at the container global setup is about to start: the driver
      // is built on the first query, which is a test away.
      env: {
        DND_GRAPH_RAG_DATA: data,
        CHAT_STUB: '1',
        NEO4J_URI, NEO4J_PASSWORD,
      },
      reuseExistingServer: false,
      stdout: 'pipe',
      timeout: 120_000,
    },
    {
      command: `npm run dev -- --port ${APP_PORT} --strictPort`,
      cwd: frontend,
      url: `http://localhost:${APP_PORT}`,
      env: { VITE_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
