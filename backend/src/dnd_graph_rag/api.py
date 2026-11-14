"""
The FastAPI app: each package's router, plus the conversation stores.

    uv run uvicorn dnd_graph_rag.api:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from dnd_graph_rag.chat import routes as chat_routes
from dnd_graph_rag.config import get_settings
from dnd_graph_rag.graph import routes as graph_routes
from dnd_graph_rag.srd import routes as srd_routes


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Open the checkpointer and the pin/title store for the process lifetime.

    Routes reach them through ``request.app.state``.

    Args:
        app: The application whose ``state`` receives both.

    Yields:
        Control to the running server, with both connections open.
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

# The Vite dev server's origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(srd_routes.router)
app.include_router(graph_routes.router)
app.include_router(chat_routes.router)
