/**
 * Where the stack listens, and what it is called.
 *
 * Its own file because `playwright.config.ts` needs these values and must
 * not import anything heavier to get them: pulling Testcontainers into the
 * config trips Node's ESM/CJS interop, and the config is loaded once per
 * worker as well as in the main process.
 *
 * The ports are deliberately not 8000/5173: a dev session on those is then
 * neither disturbed by a test run nor mistaken for the server under test.
 * The Neo4j port is *bound* rather than assigned, because Playwright starts
 * the servers before global setup — the API has to be told where the
 * database will be before the container exists.
 */

export const API_PORT = 8001
export const APP_PORT = 5174

export const NEO4J_PORT = 7688
export const NEO4J_PASSWORD = 'e2e-password'
export const NEO4J_URI = `bolt://localhost:${NEO4J_PORT}`

export const IMAGE = 'neo4j:5.26-community'
