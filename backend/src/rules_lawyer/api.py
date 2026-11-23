"""The FastAPI app: each package's router, plus the conversation stores.

    uv run uvicorn rules_lawyer.api:app --reload

With ``RULES_LAWYER_SERVE_FRONTEND`` set, the routes move under ``/api`` and
the built frontend is served at ``/``, as the Docker image runs it.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
from pydantic import ValidationError

from rules_lawyer.chat import routes as chat_routes
from rules_lawyer.config import get_settings
from rules_lawyer.graph import routes as graph_routes
from rules_lawyer.srd import routes as srd_routes

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the checkpointer and the pin/title store for the process lifetime.

    Routes reach them through ``request.app.state``.  Also warns when
    ``CHAT_TEMPERATURE`` is set for a provider whose models deprecate it.

    Args:
        app: The application whose ``state`` receives both.

    Yields:
        Control to the running server, with both connections open.
    """
    settings = get_settings()
    # An invalid chat setting is left to fail where it is used, so the
    # endpoints that need none still start.
    try:
        chat = settings.chat
    except ValidationError:
        chat = None
    if chat and chat.temperature is not None and chat.model_provider.temperature is None:
        log.warning(
            "CHAT_TEMPERATURE=%s is set, but temperature is deprecated for %s "
            "models: it may be ignored or refused. Unset it.",
            chat.temperature, chat.model_provider.title)

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

# The frontend calls /api/..., which the Vite dev server strips before
# proxying; serving the built frontend itself, the API takes that prefix.
settings = get_settings()
prefix = "/api" if settings.serve_frontend else ""
app.include_router(srd_routes.router, prefix=prefix)
app.include_router(graph_routes.router, prefix=prefix)
app.include_router(chat_routes.router, prefix=prefix)

if settings.serve_frontend:
    # Checked after every route; a page navigation to a path with no file
    # (/chat/<id>) gets index.html, so the frontend can route it.
    app.frontend("/", directory=settings.frontend_dir, fallback="index.html")
