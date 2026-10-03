# ADR-0011 — Speech behind a route; local Whisper on CPU until a better engine is chosen

**Why.** Phase 4 needs words with timings (cuts on word boundaries, captions, silence trimming). The spec names Whisper and expects a GPU for it; this VPS has two shared cores for media work and no GPU. Most of the footage is Uzbek, where Whisper is weak: on the first real clip (161.7 s, Uzbek speech and a recited poem) the `small` model auto-detected Azerbaijani and wrote Azerbaijani orthography; forced to `uz` it still produced garbage for the first sentences. A hosted engine (OpenAI, ElevenLabs Scribe, an Uzbek STT service) may be much better but needs a key, a cost decision and a privacy decision that belong to the owner.

**Impact.** The speech contract (`transcript/1`: words with timings, segments, silences, subtitle cues) is engine-independent and versioned like `mediainfo/1`. `SPEECH_ROUTE=provider:model` picks the engine the same way the model router picks LLMs; today only `faster-whisper:<model>` exists. The local engine runs int8 on two threads, slower than real time, so transcription is its own job (`speech.transcribe`, cpu queue, priority below ingestion) with per-segment progress and cancellation. The model is fetched at deploy time into `/srv/synthcut/models`; jobs never download. Audio reaches the engine as 16 kHz float PCM decoded by our own ffmpeg (faster-whisper's PyAV path breaks with PyAV 19). Silences come from `silencedetect` on the speech track (threshold relative to the measured loudness), not from the engine, so they are deterministic and engine-independent. Subtitles (≤ 2 × 42 characters, broken at sentence ends and pauses) are written as WebVTT for the player and SRT for download.

**Measured** on the VPS (2 CPUs, int8, beam 5, the 161.7 s clip):

| Model | Language | Detected | Real-time factor | Peak RAM | Result |
|---|---|---|---|---|---|
| small | auto | az (0.72) | 1.24 | 1.0 GB | Azerbaijani orthography — unusable |
| small | uz + prompt | — | 2.03 | 1.3 GB | first sentences garbage — unusable |
| large-v3-turbo | uz + prompt | — | 2.05 | 1.7 GB | readable Uzbek; Turkish letters, one sentence skipped |
| large-v3-turbo | auto | kk (0.33) | 3.95 | 1.7 GB | Kazakh Cyrillic with hallucinations — unusable |

So detection is not trusted for Turkic languages: when it lands on a Turkic neighbour the deployment's `SPEECH_PREFERRED_LANGUAGE` (default `uz`) wins, and Uzbek output is mapped from Turkish letters to Uzbek Latin (ş→sh, ç→ch, ı→i, ə→a, ö→o‘, ğ→g‘). A public benchmark on conversational Uzbek (avazibra/uzbek-stt-bench, Sept 2026) puts hosted engines at 15–28 % WER (ElevenLabs Scribe v2 19.8 %, with word timestamps); Whisper was not in it.

**Alternatives.** Whisper inside the ingest pass (would hold the proxy hostage to a slow model); `small` for speed (unusable for Uzbek); a GPU box (not available); a hosted API now (no key, no owner decision yet).

**Decision.** Ship the engine-independent contract with local `large-v3-turbo` (int8, beam 5, VAD, no conditioning on previous text, detection corrected towards Uzbek, a Latin-script Uzbek prompt), and add a hosted engine as one more provider when the owner picks one — at ~2× real time on two shared cores, a 10-minute interview takes ~20 minutes locally.
