<div align="center">

<img src="frontend/src/logo.svg" alt="" width="96" height="96">

# Rules Lawyer

[![CI](https://github.com/itsmariodias/rules-lawyer/actions/workflows/ci.yml/badge.svg)](https://github.com/itsmariodias/rules-lawyer/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/gh/itsmariodias/rules-lawyer/graph/badge.svg)](https://codecov.io/gh/itsmariodias/rules-lawyer)
[![License MIT](https://img.shields.io/github/license/itsmariodias/rules-lawyer?color=blue)](LICENSE.md)
[![Python 3.12+](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fitsmariodias%2Frules-lawyer%2Fmain%2Fbackend%2Fpyproject.toml&logo=python&logoColor=white&color=3776AB)](backend/pyproject.toml)
[![Node 22](https://img.shields.io/badge/node-22-5FA04E?logo=nodedotjs&logoColor=white)](.github/workflows/ci.yml)
[![Neo4j 5.26](https://img.shields.io/badge/neo4j-5.26-4581C3?logo=neo4j&logoColor=white)](docker-compose.yml)

</div>

Every table has one: the player who stops the game to ask whether you can
really grapple a gelatinous cube. Rules Lawyer is that player, except it
brings the book.

Ask it a rules question and it answers from the D&D 5e System Reference
Document (SRD 5.2.1), never from memory, and cites the passage behind every
claim. Click a citation and the printed page opens beside the answer, with
the lines it relied on highlighted. When the answer leads somewhere else (a
spell imposes a condition, a creature is immune to it, a class grants the
spell), you can follow the thread through the graph of how the rules connect.

Under the hood it is knowledge-graph RAG: the 364-page SRD PDF is parsed
into typed entities (spells, creatures, conditions, classes, items, rules)
and the relationships between them, loaded into Neo4j with embeddings, and
searched by a tool-calling agent.

## Features

- **Cited answers.** Every claim carries a citation to the SRD section it
  came from; invented citations are dropped, not shown.
- **The page, not a summary.** A citation opens the actual PDF in a side
  panel, scrolled to the cited lines and boxed, under a breadcrumb showing
  where they sit in the book.
- **A graph to explore.** A second tab draws the cited section's
  neighbourhood (what it references, imposes, grants or is immune to), and
  any node can be expanded or opened on the page.
- **Search by words and by meaning.** Full-text and vector search, fused, so
  exact terms ("Fire damage") match exactly and a question that shares no
  words with the book still finds the passage it is asking about.
- **Exhaustive questions.** For "which creatures can Frighten?", the agent
  writes read-only Cypher against the graph instead of guessing from a few
  passages.
- **A book that checks itself.** Parsing cross-checks the SRD against its own
  stat block index, damage dice, attack bonuses and class spell lists, and
  loading verifies the graph against the parsed document.
- **Conversations that keep.** Threads are saved, pinnable and titled, and
  the last question can be retried.

[GRAPH.md](GRAPH.md) documents every node label and relationship type.

## Run with Docker

You need **Docker** and a model provider (a **Gemini API key** by default).

### How to run

Only the compose file is needed, no clone:

```bash
mkdir rules-lawyer && cd rules-lawyer
curl -fsSLO https://raw.githubusercontent.com/itsmariodias/rules-lawyer/main/docker-compose.yml
printf 'NEO4J_PASSWORD=choose-one\nGOOGLE_API_KEY=your-key\n' > .env
docker compose up -d
```

Then open <http://localhost:8080> (`RULES_LAWYER_PORT` changes the port).
The published image (`ghcr.io/itsmariodias/rules-lawyer`) has the SRD parsed
and embedded, so the first start loads the graph in about a minute without
spending API calls. Later starts load it again only if the image changed.

### Develop with compose

From a clone, compose builds the image from your checkout:

```bash
git clone https://github.com/itsmariodias/rules-lawyer.git && cd rules-lawyer
cp .env.example .env            # set NEO4J_PASSWORD and GOOGLE_API_KEY
docker compose up -d --build
```

To load the graph again anyway:

```bash
docker compose run --rm loader rules-lawyer load
```

For the API and frontend with live reload, see [Quickstart](#quickstart).

### Configuration

Conversations are kept in the `chat` volume. The same `.env` configures
[other model providers](#other-model-providers), with two differences:

- **Ollama on your machine** is `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- **Another embedding provider** cannot use the embeddings in the image. With
  its key in `.env`, the loader embeds the SRD itself each time it loads.
  To use an `.idx` you already have, mount it in a
  `docker-compose.override.yml` beside `docker-compose.yml`, which compose
  reads on its own:

  ```yaml
  services:
    loader:
      volumes:
        - /path/to/srd_embeddings.openai.idx:/embeddings.idx:ro
      environment:
        RULES_LAWYER_EMBEDDINGS: /embeddings.idx
  ```

## Quickstart

To develop it, you need **Python 3.12+** with [uv](https://docs.astral.sh/uv/),
**Node 22+**, **Docker**, and a model provider: a **Gemini API key** by
default, or OpenAI, Anthropic or a local Ollama (see
[Other model providers](#other-model-providers)).

Copy the example environment file at the repository root and fill in the
first two values:

```bash
cp .env.example .env
```

```text
NEO4J_PASSWORD=choose-one
GOOGLE_API_KEY=your-key
```

Those two are all you need with the default provider; for another, see
[Other model providers](#other-model-providers). The rest have defaults,
listed commented out in the file; uncomment any of them to override:

| Variable | Default | What it is |
| --- | --- | --- |
| `NEO4J_PASSWORD` | none | **Required.** The database password, for the container and the app |
| `NEO4J_URI` | `bolt://localhost:7687` | |
| `NEO4J_USER` / `NEO4J_DATABASE` | `neo4j` / `neo4j` | |
| `RULES_LAWYER_EMBEDDINGS` | `data/output/srd_embeddings.idx` | An embeddings file to use instead of generating one |
| `GOOGLE_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | none | The chosen providers' keys; Google's is **required** by default. A blank value counts as unset |
| `OPENAI_BASE_URL` / `OLLAMA_BASE_URL` | OpenAI / `http://localhost:11434` | Where the server is: an OpenAI-compatible one, or Ollama |
| `CHAT_PROVIDER` / `EMBED_PROVIDER` | `google` | Who answers and who embeds: `google`, `openai`, `anthropic` (chat only) or `ollama` |
| `CHAT_MODEL` / `EMBED_MODEL` | `gemini-3.8-flash` / `gemini-embedding-001` | Required for any provider but `google` |
| `CHAT_TEMPERATURE` / `CHAT_MAX_TOKENS` | the provider's | Defaults to `0.2` for Ollama, `None` for everything else |
| `CHAT_TIMEOUT_SECONDS` | `60` | How long the model may stay silent before a turn fails |
| `EMBED_DIMENSIONS` | `1536` | Must match the model unless it can be truncated. Changing it means regenerating the embeddings |

Parsing needs neither a database nor a key, and the server starts without a
key; only asking a question does.

Build the graph and start the API, from `backend/`:

```bash
cd backend
uv sync
uv run rules-lawyer parse       # the PDF into data/output/, about 30 seconds
uv run rules-lawyer embed       # embeddings, about 2 minutes (see below)
(cd .. && docker compose up -d neo4j)   # Neo4j Browser on :7474
uv run rules-lawyer load        # load the graph and verify it
uv run uvicorn rules_lawyer.api:app --reload
```

Then the app, from `frontend/`:

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Ask it a rules question and click a citation.

**Embeddings without spending API calls.** If someone has given you an
`srd_embeddings.idx`, skip `embed` and point at it instead:

```text
RULES_LAWYER_EMBEDDINGS=/path/to/srd_embeddings.idx
```

Re-running `embed` after a re-parse only embeds sections whose text changed.

### Other model providers

The chat and the embeddings each have a provider. Install its package from
`backend/`, then set it in `.env`:

```bash
uv sync --extra openai          # or anthropic, ollama; --all-extras for every one
```

```text
CHAT_PROVIDER=anthropic
CHAT_MODEL=claude-sonnet-5-5
ANTHROPIC_API_KEY=your-key
```

| Provider | Chat | Embeddings | Settings |
| --- | --- | --- | --- |
| `google` (default) | yes | yes | `GOOGLE_API_KEY` |
| `openai` | yes | yes | `OPENAI_API_KEY`; `OPENAI_BASE_URL` for a compatible server (LM Studio, vLLM, OpenRouter) |
| `anthropic` | yes | no | `ANTHROPIC_API_KEY` |
| `ollama` | yes | yes | no key; `OLLAMA_BASE_URL` (default `http://localhost:11434`) |

The chat model must support tool calling; with Ollama, `qwen3` or
`llama3.1` does. The two providers are independent: Claude can answer over
Gemini's embeddings, with `ANTHROPIC_API_KEY` for the chat and
`GOOGLE_API_KEY` for embedding questions.

Embeddings from another provider are a different vector space, so the
shared `srd_embeddings.idx` cannot be used with them. Each provider keeps
its own file (`srd_embeddings.ollama.idx`), so the Gemini one is never
overwritten. Set `EMBED_DIMENSIONS` to the model's width unless it can be
truncated (Gemini and OpenAI's `text-embedding-3` can), then embed and load:

```text
EMBED_PROVIDER=ollama
EMBED_MODEL=nomic-embed-text
EMBED_DIMENSIONS=768
```

```bash
uv run rules-lawyer embed && uv run rules-lawyer load
```

`nomic-embed-text` is sent the `search_document: ` and `search_query: `
prefixes its model card asks for; an `.idx` made without them is
re-embedded.

Without the embedding provider's key, search is lexical only.

## Project structure

```text
data/
  source/          the SRD PDF
  output/          generated: srd_hierarchy.{json,md,anchors.json}, srd_embeddings.idx
  chat/            saved conversations (SQLite)

backend/src/rules_lawyer/
  cli.py           rules-lawyer parse | embed | load
  api.py           the FastAPI app
  srd/             PDF to a validated JSON document of entities and edges
  graph/           that document and its embeddings into Neo4j
  chat/            the agent, its tools, retrieval and conversation storage

frontend/          React + Vite chat UI, proxying /api to :8000
e2e/               Playwright tests over the whole stack
```

[`backend/`](backend/README.md), [`frontend/`](frontend/README.md) and
[`e2e/`](e2e/README.md) each have a README covering their layout and commands,
tests included.

## Licence

The code is [MIT](LICENSE.md).

The SRD 5.2.1 is published by Wizards of the Coast under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Anything derived
from it, including the generated JSON, carries that licence and its
attribution requirement. [NOTICE.md](NOTICE.md) carries the attribution
statement the SRD requires, and names what it applies to.

This work includes material from the System Reference Document 5.2.1
("SRD 5.2.1") by Wizards of the Coast LLC, available at
<https://www.dndbeyond.com/srd>. The SRD 5.2.1 is licensed under the Creative
Commons Attribution 4.0 International License, available at
<https://creativecommons.org/licenses/by/4.0/legalcode>.
