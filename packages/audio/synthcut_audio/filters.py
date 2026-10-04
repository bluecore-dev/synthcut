"""``mix/1`` → FFmpeg filters. The voice chain follows the spec's order;
loudness is two-pass ``loudnorm`` (measure, then correct linearly) so the
target is met without pumping."""

from __future__ import annotations

import json
import re

from synthcut_schemas.grade import MixPlan

NOISE_REDUCTION_DB = {"light": 6, "medium": 12, "strong": 20}


def voice_filters(plan: MixPlan, *, noise_floor_db: float | None = None) -> list[str]:
    v = plan.voice
    chain: list[str] = []
    if v.highpass_hz:
        chain.append(f"highpass=f={v.highpass_hz:g}:poles=2")
    if v.denoise != "off":
        nf = -50.0 if noise_floor_db is None else max(-80.0, min(-20.0, noise_floor_db))
        chain.append(f"afftdn=nr={NOISE_REDUCTION_DB[v.denoise]}:nf={nf:.0f}:tn=1")
    for band in v.eq:
        chain.append(f"equalizer=f={band.freq:g}:t=q:w={band.q:g}:g={band.gain_db:g}")
    if v.compressor is not None:
        c = v.compressor
        chain.append(
            f"acompressor=threshold={c.threshold_db:g}dB:ratio={c.ratio:g}:attack={c.attack_ms:g}"
            f":release={c.release_ms:g}:makeup={c.makeup_db:g}dB"
        )
    if v.deesser > 0:
        chain.append(f"deesser=i={v.deesser:g}:m=0.5:f=0.5:s=o")
    return chain


def loudnorm_measure(plan: MixPlan) -> str:
    lo = plan.loudness
    return f"loudnorm=I={lo.target_lufs:g}:TP={lo.true_peak_db:g}:LRA={lo.lra:g}:print_format=json"


def parse_loudnorm(log: str) -> dict[str, str]:
    """The JSON block ``loudnorm`` prints at the end of a measuring pass."""
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", log, flags=re.S)
    if not blocks:
        raise ValueError("no loudnorm measurement in the FFmpeg log")
    return json.loads(blocks[-1])


def loudnorm_apply(plan: MixPlan, measured: dict[str, str]) -> str:
    lo = plan.loudness
    return (
        f"loudnorm=I={lo.target_lufs:g}:TP={lo.true_peak_db:g}:LRA={lo.lra:g}"
        f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true:print_format=summary"
    )


def ducked_mix(voice: str, music: str, plan: MixPlan, out: str = "mix") -> str:
    """Voice over music, the music ducked whenever the voice speaks (spec:
    "Voice music'dan ustun turadi. Music avtomatik duck qilinadi")."""
    d = plan.ducking
    if d is None:
        return f"[{voice}][{music}]amix=inputs=2:normalize=0:duration=first[{out}]"
    ratio = max(2.0, min(20.0, 10 ** (-d.amount_db / 20)))  # how hard the music yields
    return (
        f"[{voice}]asplit=2[vkey][vmain];"
        f"[{music}][vkey]sidechaincompress=threshold=0.02:ratio={ratio:.1f}:attack={d.attack_ms:g}"
        f":release={d.release_ms:g}:makeup=1[ducked];"
        f"[vmain][ducked]amix=inputs=2:normalize=0:duration=first[{out}]"
    )
