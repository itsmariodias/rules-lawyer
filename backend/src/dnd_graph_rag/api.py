"""
The FastAPI app: one router per stage, plus the conversation stores.

Each package owns its routes; this module only assembles them.  Routes are
never imported by a package's ``__init__``, so importing a pipeline pulls in
no web framework.

    uv run uvicorn dnd_graph_rag.api:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from .chat import routes as chat_routes
from .config import get_settings
from .graph import routes as graph_routes
from .srd import routes as srd_routes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Hold the checkpointer (conversation turns) and the store (pins) open for
    the life of the process.

    Both own a SQLite connection, so they are opened once here rather than
    per request; the routes reach them through ``request.app.state``.
    """
    settings = get_settings()
    settings.chat_dir.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(
            str(settings.checkpoint_path)) as checkpointer, \
            AsyncSqliteStore.from_conn_string(
                str(settings.store_path)) as store:
        await store.setup()
        app.state.checkpointer = checkpointer
        app.state.store = store
        yield


app = FastAPI(
    title="D&D SRD graph RAG",
    version="0.1.0",
    summary="Extracts the SRD, loads the knowledge graph, and answers from it.",
    lifespan=lifespan,
)

# For the Vite dev server, which is a different origin.  A built frontend is
# served from here, so this matches nothing in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(srd_routes.router)
app.include_router(graph_routes.router)
app.include_router(chat_routes.router)
