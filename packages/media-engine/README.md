# media-engine — Phase 3

Deterministic FFmpeg / FFprobe layer (spec §21): probe, proxies, thumbnails,
audio extraction, shot detection, color metadata. Agents never call it
directly — workers run it for jobs (rule 20: AI decides, engines execute).
