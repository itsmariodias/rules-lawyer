/**
 * Start a Neo4j container and load the artifact into it.  Without Docker or an
 * artifact the run is skipped, not failed.  The returned function is the
 * global teardown; Testcontainers' reaper covers a crash.
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
         'cd backend && uv run rules-lawyer parse')
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
 * Note if the development Neo4j is also running.  Short of memory, macOS
 * suspends the browser's network service, killing streamed turns.
 */
async function warnAboutCompany() {
  if (!(await listening(7687))) return
  console.warn('\ne2e: something is already serving Neo4j on 7687, probably the'
               + '\n     development database, which this suite does not use.'
               + '\n     If turns fail with net::ERR_NETWORK_IO_SUSPENDED,'
               + '\n     `docker compose stop neo4j` frees its memory.\n')
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

/**
 * Needs neither the database nor a key, so it answers as soon as the API is
 * up.
 */
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
