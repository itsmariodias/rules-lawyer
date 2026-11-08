/**
 * Ports and names, kept dependency-free: the config is loaded in every worker,
 * and importing Testcontainers there breaks ESM/CJS interop.  Neo4j's port is
 * fixed because the API starts before the container exists.
 */

export const API_PORT = 8001
export const APP_PORT = 5174

export const NEO4J_PORT = 7688
export const NEO4J_PASSWORD = 'e2e-password'
export const NEO4J_URI = `bolt://localhost:${NEO4J_PORT}`

export const IMAGE = 'neo4j:5.26-community'
