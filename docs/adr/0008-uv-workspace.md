# ADR-0008 — A uv workspace that mirrors the spec's layout

**Why.** The spec's tree (`apps/*`, `packages/*`, `agents/*`) has hyphenated names that are not importable Python modules, and the boundaries matter (agents must not import the media engine).

**Impact.** Each directory is a workspace member with its own `pyproject.toml` and one `synthcut_*` module (`packages/media-engine` → `synthcut_media`). One lockfile; Docker installs the members as wheels into `/opt/venv`. `packages/core` is added for the models and queue shared by api, worker and bot.

**Decision.** uv workspace with `uv_build`.
