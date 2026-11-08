/**
 * A throwaway Neo4j container loaded from this checkout's artifact, rather
 * than the docker-compose database.  The port is fixed because Playwright
 * starts the API before global setup; the API connects lazily on its first
 * query.
 */

import { Neo4jContainer, type StartedNeo4jContainer } from '@testcontainers/neo4j'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'

import { IMAGE, NEO4J_PASSWORD, NEO4J_PORT, NEO4J_URI } from './ports'

const run = promisify(execFile)

export async function startNeo4j(): Promise<StartedNeo4jContainer> {
  return new Neo4jContainer(IMAGE)
    .withPassword(NEO4J_PASSWORD)
    .withExposedPorts({ container: 7687, host: NEO4J_PORT })
    // Neo4j defaults its heap from host memory; this graph needs far less.
    .withEnvironment({
      NEO4J_server_memory_heap_initial__size: '512m',
      NEO4J_server_memory_heap_max__size: '512m',
      NEO4J_server_memory_pagecache_size: '256m',
    })
    .withStartupTimeout(180_000)
    .start()
}

/**
 * Load the artifact with `srd-graph-load`, which exits non-zero if
 * verification fails.
 */
export async function loadGraph(backend: string, data: string): Promise<void> {
  await run('uv', ['run', 'srd-graph-load'], {
    cwd: backend,
    env: {
      ...process.env,
      DND_GRAPH_RAG_DATA: data,
      NEO4J_URI, NEO4J_PASSWORD,
    },
    // The load is 4260 nodes and 11442 relationships, then 68 checks.
    timeout: 600_000,
    maxBuffer: 32 * 1024 * 1024,
  })
}
