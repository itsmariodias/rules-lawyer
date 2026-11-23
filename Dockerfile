# syntax=docker/dockerfile:1.7

# Rules Lawyer as one image: the API and the built frontend on one port, the
# SRD parsed at build time and the shared Gemini embeddings downloaded, so
# loading the graph needs no API key. Neo4j runs beside it
# (docker-compose.yml).

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.13.4

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# The frontend build and the parsed artifact are the same on every platform,
# so both run on the builder's own; an arm64 image never parses under QEMU.
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY frontend/ ./
RUN npm run build

FROM --platform=$BUILDPLATFORM python:${PYTHON_VERSION}-slim AS artifact
COPY --from=uv /uv /bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev
COPY data/source/ /app/data/source/
# Also fails the build if the book disagrees with itself.
RUN .venv/bin/rules-lawyer parse

# The runtime's environment, built where it runs. An editable install:
# config.py finds the repository root (/app) from its own path, and data/
# and frontend/dist under it. uv's cache is mounted, never stored, and uv
# itself stays behind. No PyMuPDF (the pdf group): the artifact is parsed.
FROM python:${PYTHON_VERSION}-slim AS backend
COPY --from=uv /uv /bin/
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --all-extras --no-install-project
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --all-extras

FROM python:${PYTHON_VERSION}-slim
ENV PATH=/app/backend/.venv/bin:$PATH \
    RULES_LAWYER_SERVE_FRONTEND=true
RUN useradd --create-home --uid 1000 app
WORKDIR /app/backend
COPY --from=backend /app/backend/ ./
COPY data/source/ /app/data/source/
# output/ is the app user's, for a load that embeds with another provider.
COPY --from=artifact --chown=app:app /app/data/output/ /app/data/output/
COPY --from=frontend /app/frontend/dist/ /app/frontend/dist/

# The vectors for the parsed artifact, from a release asset. A new asset
# (after a parser change alters section text) changes both values.
ARG EMBEDDINGS_URL=https://github.com/itsmariodias/rules-lawyer/releases/download/embeddings-v1/srd_embeddings.idx
ARG EMBEDDINGS_SHA256=541e3fb5af2bcc52e36e6044974022c5bb5fd6ada81eae199a4b1ff3d90774f9
ADD --checksum=sha256:${EMBEDDINGS_SHA256} --chown=app:app ${EMBEDDINGS_URL} /app/data/output/srd_embeddings.idx

RUN mkdir /app/data/chat && chown app:app /app/data/chat
USER app

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"]
CMD ["uvicorn", "rules_lawyer.api:app", "--host", "0.0.0.0", "--port", "8000"]
