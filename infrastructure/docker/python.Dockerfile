# syntax=docker/dockerfile:1.7
# One image for api, worker, bot and migrations (different commands).
# Built from the repository root: docker build -f infrastructure/docker/python.Dockerfile .

FROM python:3.12-slim-trixie AS base
# Lets the deploy scripts clean up *only* SynthCut's dangling images on the
# shared host (docker image prune --filter label=...), never other projects'.
LABEL com.synthcut.project="synthcut"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH
COPY --from=ghcr.io/astral-sh/uv:0.12.22 /uv /usr/local/bin/uv
# Media engine (spec §21): Debian's ffmpeg has libx264, zscale (HDR tone-mapping),
# scdet and ebur128. In the base stage so the test image runs the same binary.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 synthcut \
 && useradd --system --uid 10001 --gid synthcut --home-dir /app --shell /usr/sbin/nologin synthcut
WORKDIR /app

FROM base AS sources
COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY agents ./agents
COPY apps/api ./apps/api
COPY apps/worker ./apps/worker
COPY apps/bot ./apps/bot

# Runtime: every workspace package installed as a regular wheel into /opt/venv,
# so the final image carries the venv only — no source tree, no dev tools.
FROM sources AS build
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-editable

FROM base AS app
COPY --from=build /opt/venv /opt/venv
RUN mkdir -p /scratch /disk-probe && chown synthcut:synthcut /scratch
USER synthcut
CMD ["python", "-m", "synthcut_api.main"]

# Motion graphics (Phase 7): the Remotion app bundled once, with its headless
# Chrome. Built from the same Debian release as the Python images.
FROM node:22-trixie-slim AS remotion
WORKDIR /opt/remotion
COPY apps/remotion/package.json apps/remotion/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY apps/remotion/ ./
RUN npx remotion bundle src/index.ts --out-dir build \
 && npx remotion browser ensure \
 && rm -rf out .remotion-cache

# Libraries Chrome Headless Shell needs at run time (Debian 13 names).
FROM app AS chrome-runtime
USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libnss3 libdbus-1-3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libgbm1 \
      libasound2t64 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libpango-1.0-0 libcairo2 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
COPY --from=remotion /usr/local/bin/node /usr/local/bin/node
COPY --from=remotion /opt/remotion /opt/remotion

# Media worker: FFmpeg, Whisper, OpenCV and Remotion (queues cpu + render).
FROM chrome-runtime AS media
ENV REMOTION_DIR=/opt/remotion
USER synthcut

# Test image: same code plus dev dependencies and the test suite.
FROM sources AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages
COPY tests ./tests
# The real Remotion render test runs here too (tests/unit/test_remotion.py).
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libnss3 libdbus-1-3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libgbm1 \
      libasound2t64 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libpango-1.0-0 libcairo2 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
COPY --from=remotion /usr/local/bin/node /usr/local/bin/node
COPY --from=remotion /opt/remotion /opt/remotion
ENV SYNTHCUT_REMOTION_DIR=/opt/remotion
CMD ["pytest", "-q", "-p", "no:cacheprovider", "tests"]
