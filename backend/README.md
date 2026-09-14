# dnd-graph-rag backend

The Python half of the monorepo: the SRD extraction pipeline, the Neo4j
loader, and the FastAPI service the frontend talks to. See the
[project README](../README.md) for what the whole thing does and
[GRAPH.md](../GRAPH.md) for the graph schema.

Run everything from this directory; `data/` and `.env` are read from the
repository root.

```bash
uv sync

uv run srd-parse                                # PDF  -> data/output/srd_hierarchy.{json,md}
uv run srd-embed                                # artifact -> srd_embeddings.idx (needs a key)
uv run srd-graph-load                           # artifact + vectors -> Neo4j, then verify
uv run pytest
uv run uvicorn dnd_graph_rag.api:app --reload   # http://127.0.0.1:8000/docs
```

Neo4j itself is started from the repository root with
`docker compose up -d neo4j`.

`srd-graph-load` requires the embeddings and will not load a graph without
them. `srd-embed` generates them from a `GOOGLE_API_KEY`; if you have the
`srd_embeddings.idx` file instead, set `DND_GRAPH_RAG_EMBEDDINGS` to its path
and skip that step. Everything else, the parse, the server and the tests,
needs neither a key nor the file.

## Layout

```text
src/dnd_graph_rag/
  config.py   settings: DND_GRAPH_RAG_* paths, NEO4J_*, CHAT_*
  api.py      FastAPI app; assembles each package's router
  srd/        stage 1: PDF to artifact
  graph/      stage 2: artifact to Neo4j
  chat/       stage 3: graph to answers
tests/        one file per module, in the package's own shape:
              tests/srd/, tests/graph/, tests/chat/, plus test_config.py
              and test_api.py.  Unit tests need nothing; the ones wanting
              the artifact or Neo4j skip without them.
```
