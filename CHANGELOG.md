# Changelog

All notable changes, phase by phase. Releases are deployed as
`YYYYMMDD-HHMMSS-<commit>`; dates are UTC.

## [Unreleased]

## Tez montaj, final render, QA, delivery · 2026-10-04

- "Tez montaj" — a rule-based editor (no model): speech kept and pauses over 0.6 s cut, black / frozen shots dropped, B-roll from usable shots of footage without speech, target length stopped on a phrase boundary, face-aware reframing to the preset, vertical footage fitted over a blurred copy in landscape frames, shot-matched grades and the measured voice mix in the plan. The Director stage is marked skipped until an agent decides.
- `edit_plans` (append-only versions) and `renders` (one per plan version + preset) — migration 0005.
- Final render from the originals: per-clip segments (colour → Rec.709, placement, grade LUT, exact frames and samples), concat, Remotion layer, two-pass loudness over the timeline with SFX, x264 / AAC master per preset.
- QA on the file (`qa/1`): resolution, frame rate, duration, codecs, loudness, true peak, black frames, frozen picture, silences, decode errors.
- Telegram delivery: the video sent to the owner's chat (`sendVideo`), a chat-sized copy when the master is over 50 MB.
- Mini App: Tez montaj card, Timeline, Versions, Preview and Render History tabs; tabs now open per built stage instead of a phase number.

## Phase 8 — colour and audio engines · 2026-10-04

- `grade/1` and `mix/1` contracts (the spec's field names).
- `synthcut_color`: Apple Log and S-Log3 curves and gamuts from their publications, BT.1886 display curve, exposure / white balance in linear light, filmic tone curve for Log, contrast and saturation, six formula-based looks; baked into one 3D LUT per clip; automatic grades with Uzbek notes; shot matching.
- `synthcut_audio`: voice measurement (speech level, noise floor, SNR, clipping), automatic mix plans, voice chain (high-pass, noise reduction, EQ, compressor, de-esser), two-pass loudness to −14 / −16 / −23 LUFS, sidechain ducking — verified by measuring FFmpeg's output.
- Enhance preview: automatic grade + voice cleanup on any clip, before/after slider, notes and MP4 download in the Mini App.

## Phase 7 — motion graphics engine · 2026-10-04

- Remotion app (`apps/remotion`): one transparent `Overlay` composition, the 15 registry widgets, a shared enter / exit animation system, bundled Montserrat / Inter with Uzbek Latin and Cyrillic coverage, Studio previews per widget.
- Caption engine: transcript words mapped through the edit to the output timeline, short lines (never across a cut), four styles — dynamic, karaoke, minimal, bold — inside platform safe zones.
- Typed props for every component (`E_COMPONENT_PROPS` now enforced); TypeScript types generated from the Python registry.
- Procedural SFX library (pop, whoosh, ding, tick, notify) synthesised with FFmpeg.
- Layer rendered as transparent PNG frames that FFmpeg composites directly (no intermediate encode: the first production preview took 24 min with a ProRes layer).
- Caption preview: animated captions burned into any transcribed clip, with player and MP4 download in the Mini App.
- Media image: Node, the Remotion bundle and Chrome Headless Shell; the media worker takes `cpu` and `render`.

- Deploys keep 3 releases instead of 5; SynthCut images carry a label so only their own dangling images are pruned on the shared host.

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
