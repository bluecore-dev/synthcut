"""Measured voice → an automatic ``mix/1`` (the Audio agent's starting point)."""

from __future__ import annotations

from typing import Literal

from synthcut_schemas.grade import AudioMeasure, Compressor, EqBand, Loudness, MixPlan, VoiceChain

Target = Literal["social", "youtube", "podcast", "broadcast"]

TARGETS: dict[str, tuple[float, float, str]] = {
    "social": (-14.0, -1.0, "Instagram / TikTok / Telegram"),
    "youtube": (-14.0, -1.0, "YouTube"),
    "podcast": (-16.0, -1.0, "podkast"),
    "broadcast": (-23.0, -2.0, "TV (EBU R128)"),
}
_LEVELS = ["off", "light", "medium", "strong"]


def denoise_level(m: AudioMeasure) -> str:
    if m.noise_floor_db is None:
        return "off"
    nf = m.noise_floor_db
    level = 0 if nf < -60 else 1 if nf < -50 else 2 if nf < -42 else 3
    if m.snr_db is not None and m.snr_db < 15 and level < 3:
        level += 1  # noise close to the voice: clean harder
    return _LEVELS[level]


def auto_mix(m: AudioMeasure, *, target: Target = "social", denoise: str | None = None) -> MixPlan:
    lufs, peak, label = TARGETS[target]
    notes: list[str] = []
    level = denoise or denoise_level(m)
    if level != "off":
        notes.append(
            f"Shovqin tozalash: {level}"
            + (
                f" (fon {m.noise_floor_db:.0f} dBFS"
                + (f", SNR {m.snr_db:.0f} dB" if m.snr_db is not None else "")
                + ")"
                if m.noise_floor_db is not None
                else ""
            )
        )
    speech = m.speech_db if m.speech_db is not None else -24.0
    compressor = Compressor(
        threshold_db=round(max(-40.0, min(-10.0, speech + 2)), 1),
        ratio=3.0,
        attack_ms=10,
        release_ms=150,
        makeup_db=2.0,
    )
    voice = VoiceChain(
        highpass_hz=80,
        denoise=level,  # type: ignore[arg-type]
        # Gentle dialogue EQ: less boxiness, more presence.
        eq=[EqBand(freq=300, gain_db=-2.0, q=1.0), EqBand(freq=3000, gain_db=2.0, q=1.0)],
        compressor=compressor,
        deesser=0.3 if m.speech_ratio > 0.05 else 0.0,
    )
    if m.integrated_lufs is not None:
        notes.append(f"Balandlik: {m.integrated_lufs:.1f} → {lufs:.0f} LUFS ({label})")
    else:
        notes.append(f"Balandlik: {lufs:.0f} LUFS ({label})")
    if m.clipped_ratio > 0.0005:
        notes.append(
            f"Ogohlantirish: yozuvda {m.clipped_ratio * 100:.2f}% namuna kliplangan — buni tiklab bo'lmaydi"
        )
    return MixPlan(voice=voice, loudness=Loudness(target_lufs=lufs, true_peak_db=peak), notes=notes)
