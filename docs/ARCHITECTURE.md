# SynthCut — Architecture (canonical)

> AI-orchestrated professional video post-production OS.
> This document is the source of truth for how SynthCut is built. Decisions
> that change it get an ADR in `docs/adr/` (**why → impact → alternatives → decision**).

Status: **Phase 0–3 built and deployed** (architecture, foundation, resumable upload,
media ingestion). Phases 4–12 are designed here and land one by one (§15).

---

## 1. Principles

**AI decides; deterministic engines execute** (spec rule 20). Agents read
state and produce typed decisions (an `EditPlan`, a grade, a mix plan). Only
deterministic code — FFmpeg, Remotion, the storage layer — touches media.

How the 20 non-negotiable rules are enforced in code:

| # | Rule | Where it is enforced |
|---|------|---------------------|
| 1, 15 | Originals never destroyed | `synthcut_storage.keys`: originals only via multipart create/complete; `put_derived_*`/`delete_derived` refuse `originals/` keys; unparseable keys count as protected |
| 2, 49 | Uploads never pass through the API | Presigned part URLs straight to storage; nginx caps the API at 1 MB bodies |
| 3, 4 | LLM never touches paths or shells | `synthcut_agent_sdk.tools.assert_safe_input_model`: tool inputs with path/command/sql fields or `Path` types are refused at registration |
| 5 | Typed tools | Every tool has Pydantic in/out models (`extra="forbid"`); invalid args return `invalid_input` to the model |
| 6 | EditPlan validated | `synthcut_timeline.validate_plan` / `ensure_valid` |
| 7 | Every render passes QA | QA agent + `validate_plan` before render (Phase 9/11) |
| 8 | Bounded reflection | Agent loop bounded by `max_steps` and `max_cost_usd`; reflection max 3 (Phase 9) |
| 9 | Idempotent workers | `jobs.idempotency_key` UNIQUE; handlers write deterministic keys / upserts |
| 10 | Observable | `events` log + `jobs` table + JSON logs (§13) |
| 11, 18 | Replaceable models | `synthcut_model_router` routes *roles* to `provider:model` chains from config |
| 12 | Versioned timeline | `schema_version: "editplan/1"` + `load_plan()` upgrader chain |
| 13 | Storage is source of truth | Assets reference storage keys; ListParts decides upload progress |
| 14 | NVMe is scratch | Workers get a per-job scratch dir, deleted when the job ends |
| 16 | Feedback → memory | Memory agent + `record_feedback`/`update_preference` tools (Phase 10) |
| 17 | Multi-user ready | `users` table, every query owner-scoped; private via allowlist only |
| 19 | Remotion = motion only | Remotion renders overlay layers; FFmpeg composites (Phase 7/11) |

## 2. Deployment reality (ADR-0001)

The VPS is **shared** with other live products (restaurant bots, LMS, agency
platform). It has 4 vCPU, 7.8 GB RAM, ~45 GB free disk and **no GPU** — far
below the spec's suggested 8–16 vCPU / 32 GB / 200 GB NVMe. Consequences:

* SynthCut runs as one Docker Compose project with its **own** PostgreSQL,
  Redis and Garage; only 127.0.0.1 ports 3400–3403 are published; the host
  nginx gets one new server block. Nothing of the other projects is touched.
* Media workers are capped at **2 CPUs / 3 GB** so a 4K proxy encode cannot
  starve the other services; heavy GPU work (local Whisper large, vision,
  upscaling) needs a separate GPU machine later — the queue design already
  routes it to a `gpu` queue (§9).
* Disk is guarded: app quota **25 GiB**, Garage hard limit **30 GiB**, and an
  upload is refused if it would leave less than **8 GiB** free on the shared
  disk. The 20–50 GB projects of the spec need a bigger disk or external S3 —
  a configuration change (`S3_ENDPOINT_*`), not a rewrite.

Domain: **`synthcut.socialmarketing.uz`** (A record → 185.2.101.47, Let's
Encrypt via webroot, auto-renewed by `certbot.timer`). Changing the domain =
DNS record + `SYNTHCUT_DOMAIN`, `PUBLIC_BASE_URL`, `S3_ENDPOINT_PUBLIC` in
`.env` + re-running `activate.sh` (it obtains the certificate and the bot
re-registers its webhook and menu button on start).

## 3. Components

```
Telegram ──▶ Bot (aiogram, webhook) ─┐
   │                                 │        ┌────────────── PostgreSQL 16 (ledger)
   ▼                                 ▼        │
Mini App (React) ──HTTPS──▶ nginx ──▶ API (FastAPI) ──┼── Redis 7 (pub/sub, wake-ups, rate limits)
   │                           │                      │
   │  presigned PUT /synthcut-media/…                 └── Garage (S3) ◀── workers (cpu / io / gpu / render / llm)
   └───────────────────────────┴──────────────────────────▶ Garage
```

| Service | Image | Port (127.0.0.1) | Role |
|---|---|---|---|
| `api` | synthcut/app | 3400 | REST + SSE, auth, upload coordination |
| `web` | synthcut/web | 3401 | Mini App static build (unprivileged nginx) |
| `storage` | dxflrs/garage:v2.4.1 | 3402 | S3 API; data in `/srv/synthcut/storage` |
| `bot` | synthcut/app | 3403 | Telegram webhook |
| `worker-cpu` | synthcut/app | — | queue `cpu`, concurrency 1, 2 CPU cap |
| `worker-io` | synthcut/app | — | queues `io,llm`, scheduler, concurrency 4 |
| `postgres`, `redis` | official | — | not published |
| `migrate` | synthcut/app | — | one-shot `alembic upgrade head` before app services |

## 4. Repository

Mirrors spec §46. Python is a **uv workspace** (ADR-0008); every member
directory holds one `synthcut_*` module.

```
apps/api            synthcut_api      routers/ auth/ projects/ uploads/ renders/ telemetry/
apps/worker         synthcut_worker   maintenance/ ingestion/ analysis/ speech/ render/ delivery/
apps/bot            synthcut_bot      handlers/ keyboards/
apps/mini-app       React + TS + Vite + Tailwind 4
apps/remotion       Phase 7
packages/core       synthcut_core     settings, db, models, jobs, events, stages, projects, migrations
packages/schemas    synthcut_schemas  enums, API DTOs, event + job payload contracts
packages/timeline   synthcut_timeline EditPlan v1, validation, registry, versioning
packages/storage    synthcut_storage  key layout, immutability guard, multipart, presigning
packages/telemetry  synthcut_telemetry JSON logging, SSE stream
packages/agent-sdk  synthcut_agent_sdk AgentSpec, typed tools, permission gate, agent loop
packages/model-router synthcut_model_router roles → provider:model, pricing, failover
packages/media-engine synthcut_media    ffprobe → MediaInfo, colour detection, ffmpeg plans, runner
agents              synthcut_agents   13 agent manifests + tool catalog
infrastructure/     docker/ nginx/ garage/ deployment/ postgres/ redis/
docs/               ARCHITECTURE.md (this), ERD.md, adr/, openapi.json
tests/              unit/ integration/
```

`packages/core` is an addition to the spec's list: SQLAlchemy models and the
job queue are shared by api, worker and bot, and live in one place so Alembic
sees one metadata.

## 5. Data model

See [ERD.md](ERD.md). Implemented (migration `0001`): `users`, `projects`,
`project_stages`, `assets`, `upload_sessions`, `jobs`, `events`. Each later
phase adds its tables in its own migration. Migrations are **additive only**
(ADR-0006).

Conventions: UUIDv7 primary keys (time-ordered); `timestamptz` everywhere;
state columns are TEXT with CHECK constraints generated from the enums in
`synthcut_schemas` (add values, never rename); JSONB for open-ended payloads.

## 6. API contract (v1)

Generated OpenAPI: [`docs/openapi.json`](openapi.json). The Mini App's
TypeScript types are generated from it (`make openapi`), so Pydantic models are
the single source of truth from database to React.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/health`, `/api/v1/ready` | liveness / readiness (db, redis, storage) |
| POST | `/api/v1/auth/telegram` | initData → access token |
| POST | `/api/v1/auth/refresh` | sliding session |
| GET | `/api/v1/me` | user + storage limits |
| GET | `/api/v1/presets` | output presets (9:16, 16:9 1080p/4K, 1:1, 4:5) |
| GET/POST | `/api/v1/projects` | list / create |
| GET/PATCH | `/api/v1/projects/{id}` | detail (stages, progress, cost) / update |
| POST | `/api/v1/projects/{id}/archive` | archive |
| GET | `/api/v1/projects/{id}/assets` | assets incl. live upload state |
| GET | `/api/v1/projects/{id}/jobs` | job history |
| GET | `/api/v1/projects/{id}/events` | activity log (paged) |
| GET | `/api/v1/projects/{id}/events/stream` | SSE, resumable with `Last-Event-ID` |
| POST | `/api/v1/projects/{id}/uploads` | open or resume an upload |
| GET | `/api/v1/uploads/{sid}` | state + parts already in storage |
| POST | `/api/v1/uploads/{sid}/parts` | presigned part URLs (MD5-bound) |
| POST | `/api/v1/uploads/{sid}/progress` | progress report (dashboards on other devices) |
| POST | `/api/v1/uploads/{sid}/complete` | verify parts, assemble, queue ingest |
| DELETE | `/api/v1/uploads/{sid}` | abort |

Errors: `{"error": {"code", "message", "details"}}`; `code` is stable for the
client, `message` is Uzbek for people. Another user's project is a **404**, not
a 403 (no existence leak).

## 7. Upload protocol (ADR-0004, ADR-0005)

```
Mini App                       API                              Garage
 │ POST /projects/{p}/uploads ─▶ quota + disk guard
 │   {name,size,fingerprint}     CreateMultipartUpload ─────────▶
 │ ◀─ session {part_size, part_count, uploaded_parts:[…]}
 │ for each missing part (3 parallel):
 │   slice → MD5
 │   POST /uploads/{s}/parts {n, md5} ─▶ presign UploadPart, signed headers = content-md5;host
 │   PUT /synthcut-media/…?partNumber=n  (Content-MD5) ──────────────────────▶ verifies MD5
 │   ◀──────────────────────────────────────────── 200 ETag = md5(part) (client re-checks)
 │ POST /uploads/{s}/complete ─▶ ListParts (paginated) → exact 1..N, sizes match
 │                                CompleteMultipartUpload → HEAD size check
 │                                asset=uploaded, enqueue ingest.asset, events
```

* **Integrity**: the part MD5 is inside the signature, so storage rejects any
  body that differs (`400 InvalidDigest`, verified on Garage). The final ETag
  is the S3 composite `md5(md5₁…md5ₙ)-n`; the full-file SHA-256 is computed
  during ingestion (Phase 3).
* **Resume**: storage's ListParts is the truth. The same file picked again
  (fingerprint = SHA-256 of name|size|lastModified, falling back to
  name+size because iOS Photos changes lastModified) returns the same session;
  the client first verifies 3 already-stored parts against its own MD5s so two
  different files can never be stitched together.
* **Part size**: 16 MiB, grown so a file stays under 9 000 parts
  (5 GB → 299 parts, 50 GB → 2 981, 200 GB → 22 MiB × 8 670).
* **Expiry**: sessions idle 48 h are aborted by `maintenance.expire_uploads`;
  multipart uploads with no open session are aborted after 24 h by
  `maintenance.sweep_orphan_uploads`.
* **Same origin**: storage is proxied at `/synthcut-media/` on the Mini App's
  own host with Host and path unchanged — no CORS, one certificate.

## 8. Storage design

```
projects/<project_id>/originals/<asset_id>/source.<ext>   immutable
projects/<project_id>/{proxies,audio,thumbnails,analysis,timeline,previews,renders,exports}/<owner_id>/<name>
```

Keys are built only by `synthcut_storage.keys`: every component is a UUID, a
fixed enum or a strict pattern; the user's file name never reaches a key. The
NVMe-scratch role (spec §8) is `/srv/synthcut/scratch/<project>/<job>/`,
removed when the job ends.

Garage (ADR-0003) replaced MinIO, whose community images are no longer
published. The code speaks plain S3 (boto3, path-style, checksum calculation
`when_required`), so AWS S3 / R2 / another Garage cluster is a config change.

## 8a. Ingestion — the media engine (Phase 3, ADR-0010)

`ingest.asset` (queue `cpu`, enqueued when an upload completes) turns an
original into everything later stages need. The original is only read —
streamed from Garage over the private network — never copied to scratch:

1. **ffprobe → `MediaInfo`** (`synthcut_schemas.media`, versioned
   `mediainfo/1`): container, duration, coded *and* display size (rotation,
   anamorphic SAR), fps + VFR, codec/profile, bit depth, chroma, colour tags,
   audio, camera make/model/software. GPS coordinates are dropped
   (`has_location` only).
2. **Colour detection** (§11): PQ/HLG/Dolby Vision from tags (high), Apple Log
   from an explicit tag (high) or Apple camera + 10-bit + undeclared transfer
   (medium), other undeclared 10-bit = "Log (suspected)" (low), Rec.709 /
   Rec.2020 SDR. Phase 8 builds transforms on top; the user can correct it.
3. **SHA-256** of the original, streamed.
4. **One decode pass** of the original produces the 720p H.264 proxy
   (short side 720, never upscaled, keyframe every 2 s, ≤ 60 fps, AAC), the
   16 kHz mono FLAC speech track for Whisper (Phase 4) and an EBU R128
   loudness measurement. HDR is tone-mapped to SDR **after** scaling (zscale in
   float at 720p, not 4K); Log stays flat (no guessing a transform).
5. From the proxy: poster, a filmstrip sprite (≤ 12 tiles) and scene cuts
   (`scdet`) → shots, flashes shorter than 0.4 s merged.
6. Derived files go to deterministic keys (`proxies/`, `audio/`,
   `thumbnails/`, `analysis/`), one `media_files` row per (asset, kind) —
   re-running overwrites, never duplicates.

FFmpeg runs as an argument list (never a shell), `nice 10`, 2 threads inside
the 2-CPU worker container, with progress, cooperative cancellation and a
duration-based timeout. Corrupt/unsupported input is a permanent failure (no
retries, asset `failed`, stage shows it); I/O errors retry. When a project's
ingest stage turns `done`, the owner gets one Telegram message
(`notify.telegram`, worker → Bot API, token never in errors).

`GET /api/v1/assets/{id}` returns the typed `MediaInfo`, shots and presigned
links (proxy with HTTP range for the player, poster, filmstrip); the list
carries a poster per asset. The Mini App keeps the first presigned URL per
file until it nears expiry so images do not flash on refetch.

## 9. Queue design (ADR-0002)

PostgreSQL `jobs` is the ledger; Redis only rings the bell.

* Enqueue inside the caller's transaction; `idempotency_key` UNIQUE.
* Claim: `UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED LIMIT 1)`,
  ordered by priority (0 interactive, 1 high, 2 normal, 3 low), `run_after`,
  `created_at`; filtered by the worker's queues **and the kinds it can run**.
* Lease: 60 s, renewed every 20 s by a heartbeat thread that also carries
  progress and notices cancellation or lease loss.
* Fencing: complete/fail/heartbeat apply only `WHERE lease_owner = me`.
* Failure: retryable → backoff `15 s · 4^(attempt-1)` capped at 10 min;
  exhausted or permanent → `dead`.
* Recovery: expired leases are reaped every 30 s → `queued` (or `dead`).
* Shutdown: SIGTERM → stop claiming, 45 s grace, hand back without charging
  an attempt.
* Queues: `io`, `cpu`, `gpu`, `render`, `llm`. Periodic jobs are enqueued
  with `kind@period-bucket` keys, so any number of schedulers enqueue once.

## 10. Event schema

`events` (bigint identity id = SSE id): `project_id, type, level, source,
message, data, job_id, created_at`. Persisted types: `project.*`, `upload.*`,
`stage.updated`, `job.queued|started|succeeded|retrying|failed|cancelled`.
Ephemeral (Redis only): `upload.progress`, `job.progress`.

Persisted events are published to Redis **after** commit. The SSE stream
subscribes first, replays from the table, then streams live; a catch-up query
every 10 s with a 90 s look-back closes gaps from out-of-order commits, and a
bounded set of sent ids prevents duplicates.

## 11. Agents (spec §14-29)

* `AgentSpec(name, mission, model_role, tools, phase, max_steps, max_cost_usd)`;
  13 manifests in `agents/` (master, video_analysis, director, editor, color,
  audio, motion, caption, research, qa, reflection, memory, render).
* Tool catalog: 34 tools with scope `read | plan | media | external` and the
  phase that implements them. Tests guarantee: only Research has `external`
  tools, only Render renders, Director cannot start media jobs.
* `run_agent` — our own loop (ADR-0009): permission gate on every call, all
  tool results of a turn in one message, never runs tools from a truncated
  turn, stops on refusal, `max_steps`, or `max_cost_usd`.
* Model Router: roles `reasoning | planning | vision | fast` → ordered
  `provider:model` chains from `MODEL_ROUTES`; failover only for errors another
  target can fix; cost from a provider-independent price table. Default chain:
  `anthropic:claude-opus-5` for every role, until the user tunes it.

## 12. Timeline (EditPlan v1)

`synthcut_timeline.EditPlan`: `sequence {fps,width,height,duration}`,
`video_tracks[]` (main / broll / overlay), `audio_tracks[]` (voice / music /
sfx / ambience, ducking), `graphics[]` (registry components only), `captions`,
`global_effects`, `notes`. Times are seconds, validated against the frame grid
(`snap_to_frames` normalises). Sources are asset ids, never paths.

`validate_plan` reports all issues at once with paths: `E_OVERLAP`,
`E_MAIN_GAP` (black frames), `E_MAIN_COVERAGE`, `E_DURATION_MISMATCH`,
`E_OUT_OF_SEQUENCE`, `E_UNKNOWN_ASSET`, `E_ASSET_KIND`, `E_SOURCE_RANGE`,
`E_UNKNOWN_COMPONENT`, `E_COMPONENT_PROPS`, `E_DUPLICATE_ID`,
`E_DUPLICATE_TRACK`, `E_TRANSITION_TOO_LONG`, `E_KEYFRAME_RANGE`,
`E_FADE_RANGE`, `W_FRAME_ALIGNMENT`, `W_AUDIO_OVERLAP`.

## 13. Security model

* **Auth**: Mini App sends raw `initData`; the API verifies the HMAC with the
  bot token (`WebAppData` key), rejects data older than 1 h, then issues a 12 h
  HS256 token (sliding refresh). `initDataUnsafe` is never trusted.
* **Allowlist**: `AUTHORIZED_TELEGRAM_USER_IDS`, checked at login **and on
  every request**; empty list = nobody. The bot answers strangers with their
  Telegram id so the owner can add them.
* **Ownership**: every project/asset/upload query is owner-scoped → 404.
* **Storage**: bucket private; presigned URLs expire in 1 h and are bound to
  key + upload id + part number + MD5; nginx allows only GET/PUT on the
  storage path.
* **Bot**: webhook only (no polling code exists), secret path +
  `X-Telegram-Bot-Api-Secret-Token`; answers 200 immediately, works in the
  background.
* **Secrets**: `/opt/synthcut/shared/.env`, 0600, generated once on the
  server, never in git. Containers run as uid 10001; ports bound to 127.0.0.1.
* **Rate limits**: login 30/min/IP, upload creation 120/min/user (Redis,
  fail-open — the cryptographic gates are elsewhere).

## 14. Observability

JSON logs on stdout (rotated 5×10 MB per container), every job's attempts,
lease owner, timings, progress, error and result in `jobs`, the project
activity log in `events`. `/api/v1/ready` checks database, Redis and storage.

## 15. Phases

| Phase | Scope | Status |
|---|---|---|
| 0 | Architecture, ERD, API contract, queue, storage, events, agent interfaces, timeline schema, security | **done** |
| 1 | FastAPI, PostgreSQL, Redis, object storage, Telegram auth, Mini App, projects | **done** |
| 2 | Resumable multipart upload, progress, pause/resume, checksum, asset registration | **done** |
| 3 | FFprobe, proxies, thumbnails, audio extraction, shot detection, color metadata | **done** |
| 4 | Whisper, word timestamps, silence, subtitles | needs a speech route (API key or local CPU model) |
| 5 | Video Analysis agent | needs `ANTHROPIC_API_KEY` |
| 6 | Master, Director, Editor, EditPlan persistence | needs `ANTHROPIC_API_KEY` |
| 7 | Remotion compositions, widget registry, subtitles | |
| 8 | Color + Audio agents, grading, mixing, ducking | |
| 9 | QA, error classifier, reflection, retries | |
| 10 | Memory, preferences, feedback | |
| 11 | Full render from originals | GPU/CPU capacity decision |
| 12 | Telegram delivery | |

## 16. Operations

* Deploy: `bash infrastructure/deployment/deploy.sh` (clean tree required) →
  release `YYYYMMDD-HHMMSS-<sha>` → build → Garage init → migrate → start →
  health check (api ready, bot, web) → automatic rollback to the previous
  image tag on failure → nginx installed only if `nginx -t` passes (else the
  previous file is restored).
* Rollback by hand: `cd /opt/synthcut/releases/<old> && SYNTHCUT_RELEASE=<old>
  docker compose --env-file /opt/synthcut/shared/.env up -d`.
* Tests on the server: `bash infrastructure/deployment/test-stack.sh` —
  throwaway PostgreSQL/Redis/Garage (tmpfs), never production.
* Browser e2e against a deployment: `tests/e2e/mini_app_e2e.py` (Chromium +
  WebKit; real initData, real nginx → Garage path, interrupt + resume). It found
  three production defects the unit and integration suites could not: the CSP
  blocking WebAssembly MD5, inlined `data:` fonts blocked by CSP, and upstream
  keep-alive races producing 502s on POSTs.
* Logs: `docker compose -p synthcut logs -f api worker-io bot`.
