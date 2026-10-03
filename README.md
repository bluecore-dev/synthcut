# SynthCut

AI-orchestrated professional video post-production OS: RAW/Log footage →
analysis → intelligent editing → color → audio → motion → captions → QA →
render, run by a team of specialist agents behind a Telegram Mini App.

**AI decides; deterministic media engines execute.**

* Architecture (canonical): [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
* Data model: [docs/ERD.md](docs/ERD.md) · Decisions: [docs/adr/](docs/adr/)
* API: [docs/openapi.json](docs/openapi.json)

## Status

| Phase | | |
|---|---|---|
| 0 Architecture | done | schemas, ERD, API contract, queue, storage, events, agent interfaces, timeline |
| 1 Foundation | done | FastAPI, PostgreSQL, Redis, Garage S3, Telegram auth, Mini App, projects |
| 2 Upload | done | resumable multipart, MD5-verified parts, pause/resume, progress, quotas |
| 3 Media engine | done | ffprobe metadata, colour detection, 720p proxy, thumbnails, speech audio, loudness, shots |
| 4 Speech | done | Whisper (local CPU, `SPEECH_ROUTE`), word timings, silences, subtitles (VTT/SRT), transcript UI |
| 5 Video intelligence | 5a done | per-shot faces/framing, camera motion, sharpness, exposure, speech, duplicates, usability; vision description waits for a model key |
| 6–12 | planned | see ARCHITECTURE.md §15 |

## Development

```bash
make sync                # Python 3.12 workspace (uv)
make test-unit           # fast, no services
make test                # + integration: local PostgreSQL + Redis, S3 via moto
make openapi             # regenerate OpenAPI + Mini App TS types after API changes
make web-dev             # Mini App on :5173, /api proxied to :3400
```

Integration tests drop and recreate the schema of `SYNTHCUT_TEST_DATABASE_URL`
— never point it at a real database. On the server, run the suite against
throwaway containers: `bash infrastructure/deployment/test-stack.sh`.

## Deployment

```bash
bash infrastructure/deployment/deploy.sh   # commit first
```

Builds a tagged release on the server, initialises storage, migrates, starts,
health-checks and rolls back automatically if the release is unhealthy.
