/**
 * The database these tests run against: a container of their own.
 *
 * Not the Neo4j from `docker-compose.yml`. That one holds whatever the last
 * `srd-graph-load` put in it, which makes a passing run mean "the graph on
 * this machine happens to be right" rather than "the artifact in this
 * checkout produces a graph the UI can answer from". A throwaway container,
 * loaded from the artifact each run, tests the whole chain: parse → load →
 * retrieve → answer → cite.
 *
 * The port is bound rather than assigned. Playwright starts `webServer`
 * before global setup, so the API is already running by the time this
 * container exists and cannot be told a port that was chosen afterwards —
 * but it opens no connection until the first query, which is a test away.
 * A fixed port is what lets those two facts coexist.
 */

import { Neo4jContainer, type StartedNeo4jContainer } from '@testcontainers/neo4j'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

import { IMAGE, NEO4J_PASSWORD, NEO4J_PORT, NEO4J_URI } from './ports'

const run = promisify(execFile)

export async function startNeo4j(): Promise<StartedNeo4jContainer> {
  return new Neo4jContainer(IMAGE)
    .withPassword(NEO4J_PASSWORD)
    // Bound, not assigned — see above.
    .withExposedPorts({ container: 7687, host: NEO4J_PORT })
    // Neo4j sizes its heap from what the machine appears to have, which on a
    // laptop already running a development instance is most of the Docker VM
    // claimed twice over. This graph is 4260 nodes and 11319 relationships:
    // the whole of it fits in a fraction of that, and the rest is better
    // left to the browser and the two servers.
    .withEnvironment({
      NEO4J_server_memory_heap_initial__size: '512m',
      NEO4J_server_memory_heap_max__size: '512m',
      NEO4J_server_memory_pagecache_size: '256m',
    })
    .withStartupTimeout(180_000)
    .start()
}

/**
 * Fill it from the artifact, with the same command a contributor runs.
 *
 * `srd-graph-load` verifies what it wrote against the artifact's own counts
 * and exits non-zero if a single check fails, so a load that returns at all
 * is a graph worth testing against.
 */
export async function loadGraph(backend: string, data: string): Promise<void> {
  await run('uv', ['run', 'srd-graph-load'], {
    cwd: backend,
    env: {
      ...process.env,
      DND_GRAPH_RAG_DATA: data,
      NEO4J_URI, NEO4J_PASSWORD,
    },
    // The load is 4260 nodes and 11319 relationships, then 64 checks.
    timeout: 600_000,
    maxBuffer: 32 * 1024 * 1024,
  })
}
