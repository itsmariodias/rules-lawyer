/**
 * End-to-end run over Vite, FastAPI and a fresh Neo4j container, with the
 * backend's fake chat model (`tests.e2e_app`) so no API key is needed.  Uses
 * its own ports (8001, 5174) and its own `.data` directory, whose `chat/` is
 * emptied each run.
 */

import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

import { API_PORT, APP_PORT, NEO4J_PASSWORD, NEO4J_URI } from './ports'

const here = __dirname
const root = path.resolve(here, '..')
const backend = path.join(root, 'backend')
const frontend = path.join(root, 'frontend')
// Created by the API's start command: this config runs in every worker, so
// it must not touch the filesystem.
const data = path.join(here, '.data')
const prepare = path.join(here, 'prepare-data.mjs')

export default defineConfig({
  testDir: './specs',
  globalSetup: './global-setup.ts',
  // One shared SQLite file and graph, so specs run serially in file order.
  workers: 1,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // Container start and load take a minute or two.
  globalTimeout: 20 * 60_000,
  // Covers `net::ERR_NETWORK_IO_SUSPENDED` under memory pressure (see
  // global-setup.ts), locally as well as in CI.
  retries: 1,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    // Vite binds `localhost`, which resolves to ::1, not 127.0.0.1.
    baseURL: `http://localhost:${APP_PORT}`,
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
          // Headless Chrome throttles timers and rendering in background
          // windows, which stalls streamed turns.
          args: ['--disable-background-timer-throttling',
                 '--disable-backgrounding-occluded-windows',
                 '--disable-renderer-backgrounding'],
        },
      },
    },
  ],
  webServer: [
    {
      // Builds the data directory and starts the server in one command.
      command: `node "${prepare}" `
               + `&& uv run uvicorn tests.e2e_app:app --port ${API_PORT}`,
      cwd: backend,
      // Needs neither the database nor a key.
      url: `http://127.0.0.1:${API_PORT}/health`,
      // The container starts later in global setup; the driver connects lazily.
      env: {
        RULES_LAWYER_DATA: data,
        // Blank, not unset, to override the root .env: otherwise every query
        // is embedded live and spends quota.  Search runs lexical-only.
        GOOGLE_API_KEY: '',
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
