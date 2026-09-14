/**
 * Bring up the database, fill it from the artifact, and hand the workers a
 * verdict on whether there is anything to test.
 *
 * Nothing here fails the run. The pytest suite skips cleanly when Neo4j is
 * absent and so does this: no Docker, or no artifact, is a skip with a line
 * saying what to do about it — not a wall of red for someone who has just
 * cloned the repository.
 *
 * The container is stopped by the function this returns, which Playwright
 * runs as global teardown. If the process dies before that, Testcontainers'
 * own reaper collects it.
 */

import type { StartedNeo4jContainer } from '@testcontainers/neo4j'
import path from 'node:path'

import { createConnection } from 'node:net'

import { API_PORT, IMAGE } from './ports'
import { loadGraph, startNeo4j } from './stack'

const here = __dirname
const backend = path.join(here, '..', 'backend')
const data = path.join(here, '.data')

const API = `http://127.0.0.1:${API_PORT}`

export default async function globalSetup() {
  process.env.E2E_READY = 'false'
  await warnAboutCompany()

  if (!(await artifactExists())) {
    skip('the artifact has not been generated',
         'cd backend && uv run srd-parse')
    return
  }

  let neo4j: StartedNeo4jContainer
  try {
    console.log(`e2e: starting ${IMAGE}…`)
    neo4j = await startNeo4j()
  } catch (failure) {
    skip(`no database could be started (${(failure as Error).message})`,
         'check that Docker is running')
    return
  }

  try {
    console.log('e2e: loading the artifact into it…')
    await loadGraph(backend, data)
  } catch (failure) {
    await neo4j.stop()
    skip(`the graph could not be loaded (${(failure as Error).message})`, '')
    return
  }

  process.env.E2E_READY = 'true'
  return async () => { await neo4j.stop() }
}

/**
 * Say something if the development database is also running.
 *
 * Two Neo4j JVMs is more memory than a laptop has to spare, and what gives
 * way is not the database: macOS suspends the browser's network service
 * under pressure, which kills whichever streamed turn was open at the time
 * and fails the test waiting on it — measured at four to six of thirty-three
 * with the development instance up, and none at all with it stopped, in half
 * the wall-clock time. The suite brings its own database, so the other one
 * is only in the way for the few minutes this takes.
 *
 * A warning rather than a refusal: it is the reader's machine, the retry
 * covers it, and a run that works slowly is better than one that will not
 * start.
 */
async function warnAboutCompany() {
  if (!(await listening(7687))) return
  console.warn('\ne2e: something is already serving Neo4j on 7687 — probably'
               + '\n     the development database, which this suite does not'
               + '\n     use and does not have the memory to sit beside.'
               + '\n     Expect suspended turns and a retry or two;'
               + '\n     `docker compose stop neo4j` makes them go away.\n')
}

function listening(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = createConnection({ port, host: '127.0.0.1' })
    const answer = (open: boolean) => { socket.destroy(); resolve(open) }
    socket.setTimeout(1000)
    socket.once('connect', () => answer(true))
    socket.once('timeout', () => answer(false))
    socket.once('error', () => answer(false))
  })
}

/** The API answers this without a database or a key, so it answers early. */
async function artifactExists(): Promise<boolean> {
  try {
    const health = await fetch(`${API}/health`).then((r) => r.json())
    return health.output_present === true
  } catch {
    return false
  }
}

function skip(why: string, remedy: string) {
  console.warn(`\ne2e: ${why}, so these tests will skip.`
               + (remedy ? `\n     ${remedy}\n` : '\n'))
}
