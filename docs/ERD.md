# SynthCut — Entity relationships

Implemented in migrations `0001_foundation` (Phase 1–2), `0002_ingestion` (Phase 3) and `0003_transcripts` (Phase 4):

```mermaid
erDiagram
    users ||--o{ projects : owns
    users ||--o{ upload_sessions : starts
    projects ||--o{ project_stages : "pipeline (13 rows)"
    projects ||--o{ assets : contains
    projects ||--o{ jobs : scopes
    projects ||--o{ events : logs
    assets ||--o| upload_sessions : "uploaded by"
    assets ||--o{ media_files : "derived files"
    assets ||--o| transcripts : "speech"
    jobs ||--o{ jobs : "parent_id"

    users {
        uuid id PK
        bigint telegram_id UK
        text username
        bool is_active
        timestamptz last_seen_at
    }
    projects {
        uuid id PK
        uuid owner_id FK
        text name "1..120"
        text preset "reels_9x16 | youtube_16x9_1080 | ..."
        smallint fps
        int target_duration_sec
        text mode "auto | assisted | manual"
        text language
        text brief
        text status "active | archived"
    }
    project_stages {
        uuid project_id PK
        text stage PK "upload ... delivery"
        text status "pending | queued | running | done | failed | ..."
        real progress "0..1"
        text detail
    }
    assets {
        uuid id PK
        uuid project_id FK
        text kind "video | audio | image | other"
        text status "uploading | uploaded | ingesting | ready | failed | cancelled"
        text storage_key UK "projects/<p>/originals/<a>/source.<ext>"
        bigint size_bytes
        text fingerprint "unique while uploading"
        text etag "S3 composite"
        text sha256 "of the original"
        jsonb media_info "MediaInfo mediainfo/1"
        text color_profile "rec709 | hlg | pq | apple_log | ..."
        text video_codec
        bool has_audio
    }
    media_files {
        uuid id PK
        uuid asset_id FK
        text kind "proxy_720p | poster | sprite | audio_speech | audio_proxy | preview | shots | mediainfo | transcript | subtitles_vtt | subtitles_srt"
        text storage_key UK "projects/<p>/<area>/<a>/<name>"
        bigint size_bytes
        jsonb metadata "tiles, interval, shots, tonemapped..."
    }
    transcripts {
        uuid id PK
        uuid asset_id FK,UK
        text status "queued | running | done | failed"
        text requested_language "auto | uz | ru | en"
        text language "detected or forced"
        text engine "provider:model"
        int word_count
        real speech_sec
        jsonb data "transcript/1: words, segments, silences, cues"
        int runs "bumped per request (idempotency key)"
    }
    upload_sessions {
        uuid id PK
        uuid asset_id FK,UK
        text s3_upload_id
        bigint part_size
        int part_count
        text status "active | completing | completed | aborted | expired | failed"
        bigint bytes_reported
        timestamptz last_activity_at
    }
    jobs {
        uuid id PK
        text kind
        text queue "io | cpu | gpu | render | llm"
        smallint priority "0..3"
        text status "queued | running | succeeded | dead | cancelled"
        text idempotency_key UK
        jsonb payload
        int attempts
        text lease_owner
        timestamptz lease_expires_at
    }
    events {
        bigint id PK "SSE id"
        uuid project_id FK
        text type
        text level
        text message
        jsonb data
    }
```

## Planned (designed now, migrated in their phase)

| Table | Phase | Key columns |
|---|---|---|
| `media_analysis` | 5 | asset_id, clip ranges, shot_type, subject, framing, motion, quality scores, semantic_description, usable_score, model, cost |
| `timeline_versions` | 6 | project_id, version (UNIQUE per project), parent_version, created_by (agent/user), reason |
| `edit_plans` | 6 | timeline_version_id, schema_version, plan JSONB (EditPlan), validation report |
| `agent_runs` | 5–6 | project_id, job_id, agent, model, status, steps, tokens in/out/cache, cost_usd, transcript ref |
| `cost_records` | 5 | project_id, agent_run_id, provider, model, usage, cost_usd — the §33 dashboard sums these |
| `renders` / `render_versions` | 11 | timeline_version_id, preset, kind (preview/final), status, storage_key, probe report — UNIQUE(timeline_version_id, preset, kind) so a job can never render twice |
| `qa_reports` | 9 | render/plan ref, findings JSONB, classification, deterministic_fix, attempts (≤ 3) |
| `feedback` | 10 | project_id, user_id, text, target ref, structured interpretation |
| `memories` / `preferences` | 10 | scope (global/user/project/session), key (e.g. `transition_density`), value, source feedback |
| `research_documents` | 10 | source url, extract, verification status, embedding ref |
| `deliveries` | 12 | render_id, chat_id, transport (bot / link), telegram message id, status |
