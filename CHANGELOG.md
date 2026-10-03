# Changelog

All notable changes, phase by phase. Releases are deployed as
`YYYYMMDD-HHMMSS-<commit>`; dates are UTC.

## [Unreleased]

## Phase 5a — measured shot analysis · 2026-10-04

- Per-shot analysis of every video (`clipanalysis/1`): shot type, people and position from YuNet faces; camera motion (static, pan, tilt, handheld) from phase correlation; sharpness, exposure, crushed / clipped areas; frozen and black frames; speech share and silent gaps (Silero VAD); retakes across the project (perceptual hash); usability score and flags.
- `asset_analyses` and `clip_analyses` tables (migration 0004); `analysis.asset` job between ingestion and transcription.
- API: `GET /assets/{id}/clips`, `GET /projects/{id}/clips`, `POST /assets/{id}/analyze`.
- Mini App: shot cards on the asset page, Analysis tab with filters, list badges.
- Calibrated on real footage: 16 shots of a 162 s clip in 51 s on two cores.

## Phase 4 — speech · 2026-10-03

- Local Whisper (`faster-whisper:large-v3-turbo`, int8 CPU) behind `SPEECH_ROUTE`; model fetched at deploy time.
- `transcript/1`: words with timings and confidence, segments, questions, silences, subtitle cues; WebVTT and SRT files.
- Language detection corrected towards Uzbek when Whisper hears a Turkic neighbour; Turkish letters mapped to Uzbek Latin.
- API: `GET /assets/{id}/transcript`, `POST /assets/{id}/transcribe`; Mini App transcript with tappable words, subtitle track, SRT download, Transcript tab.

## Phase 3 — media engine · 2026-10-03

- ffprobe normalisation (`mediainfo/1`) with rotation, VFR, bit depth, camera metadata (no GPS).
- Colour detection: Rec.709, Display P3, Rec.2020 SDR, HLG, PQ, Apple Log, Log (suspected).
- One decode pass: 720p proxy, scene cuts, 16 kHz speech track, EBU R128 loudness; HDR tone-mapping and wide-gamut → Rec.709 after scaling; keyframe-only filmstrip (fixes an OOM on ffmpeg 7.1).
- Re-ingest endpoint; Telegram notification when a project's media is ready.

## Phases 0–2 — architecture, foundation, uploads · 2026-10-02

- Architecture, ERD, API contract, ADRs; uv workspace mirroring the specification.
- FastAPI, PostgreSQL 16, Redis 7, Garage S3; Telegram initData authentication with an allowlist; Mini App; projects; webhook bot.
- Resumable multipart uploads with MD5-bound presigned parts, content-based resume fingerprint, cross-device progress, quotas and disk reserve.
- Release-per-commit deployment with health checks and automatic rollback; server-side test stack.
