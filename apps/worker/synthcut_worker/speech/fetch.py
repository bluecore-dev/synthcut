"""``python -m synthcut_worker.speech.fetch`` — put the configured local speech
model into ``SPEECH_MODELS_DIR`` before workers start (activate.sh runs it).
Idempotent; jobs never download (``local_files_only``)."""

from __future__ import annotations

import sys
from pathlib import Path

from synthcut_core.settings import get_settings
from synthcut_speech.engines import EngineUnavailable, FasterWhisperEngine, engine_for


def main() -> int:
    s = get_settings()
    models_dir = Path(s.speech_models_dir)
    try:
        engine = engine_for(s.speech_route, models_dir=models_dir, threads=1, beam_size=1)
    except EngineUnavailable as exc:
        print(f"speech: {exc}", file=sys.stderr)
        return 1
    if not isinstance(engine, FasterWhisperEngine):
        print(f"speech: {engine.route} needs no local model")
        return 0
    if engine.is_fetched():
        print(f"speech: {engine.route} already in {models_dir}")
        return 0
    path = engine.fetch()
    size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    print(f"speech: fetched {engine.route} → {path} ({size / 1024**2:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
