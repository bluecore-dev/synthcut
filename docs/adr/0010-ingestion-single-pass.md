# ADR-0010 — Ingestion in one decode pass; HDR tone-mapped, Log left flat

**Why.** Decoding a 4K HEVC/ProRes original is the expensive part of ingestion, and the VPS gives the media worker two shared cores. Separate passes for proxy, speech audio and loudness would decode it three times. Phones record HDR (HLG + Dolby Vision) by default, and Log footage looks washed out; a proxy that ignores this is useless for both people and vision models.

**Impact.** One FFmpeg run reads the original (streamed from storage, never copied) and writes the proxy, the 16 kHz speech FLAC and an EBU R128 measurement; thumbnails, the filmstrip and scene cuts are then computed from the small proxy. HDR is tone-mapped to Rec.709 after scaling to 720p (zscale in float RGB is ~16× cheaper than at 4K). Log material keeps its flat look in the proxy and is only flagged: guessing a Log→Rec.709 transform would bake an unverified decision into every later preview — that is the Color agent's job (Phase 8). Colour detection reports a confidence so a wrong guess is visible.

**Alternatives.** Download the original to scratch first (doubles disk use on a shared disk); hardware decoding (no GPU here); PySceneDetect for cuts (another dependency; `scdet` on the proxy is enough for a first shot list); proxies at 1080p (2.25× the CPU for little gain on a phone screen).

**Decision.** Single decode pass, 720p proxy, tone-map HDR, leave Log flat with a flag.
