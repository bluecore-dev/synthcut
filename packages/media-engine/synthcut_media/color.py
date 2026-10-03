"""Source color detection from container/stream tags (spec §11).

Rules, in order of how much the tags can be trusted:

* PQ (smpte2084) or HLG (arib-std-b67) transfer → HDR, high confidence.
  A Dolby Vision configuration record marks DV on top (iPhone: DV 8.4 over HLG).
* An explicit "Apple Log" marker in any tag → Apple Log, high confidence.
* 10-bit+ with an unspecified transfer in a wide (BT.2020) or untagged gamut is
  what Log footage looks like from the outside: Apple Log when the camera is
  an Apple device (medium), otherwise "Log (suspected)" (low). The user can
  correct it later; the original is never altered either way.
* BT.709-family transfer/primaries → Rec.709. Untagged 8-bit → Rec.709, low.
"""

from __future__ import annotations

from .models import ColorInfo, VideoStream

_UNSET = {"", "unknown", "unspecified", "reserved", "none"}
_SDR_709_TRC = {"bt709", "smpte170m", "bt470bg", "bt470m", "bt1361e", "gamma22", "gamma28", "iec61966-2-1"}
_709_PRIMARIES = {"bt709", "smpte170m", "bt470bg", "bt470m", "smpte240m"}


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def classify_color(
    video: VideoStream | None,
    *,
    is_image: bool,
    make: str | None,
    tag_values: list[str],
    dolby_vision: bool,
) -> ColorInfo | None:
    if video is None:
        return None
    trc = _norm(video.color_transfer)
    prim = _norm(video.color_primaries)
    depth = video.bit_depth or 8
    apple = "apple" in _norm(make)
    reasons = [f"transfer={trc or 'unset'}", f"primaries={prim or 'unset'}", f"{depth}-bit"]

    if is_image:
        if trc == "smpte2084":
            return ColorInfo(profile="pq", label="HDR · PQ", confidence="high", hdr=True, reasons=reasons)
        return ColorInfo(profile="srgb", label="sRGB", confidence="medium", reasons=reasons)

    if trc == "smpte2084":
        label = "Dolby Vision · PQ" if dolby_vision else "HDR · PQ"
        return ColorInfo(
            profile="pq", label=label, confidence="high", hdr=True, dolby_vision=dolby_vision, reasons=reasons
        )
    if trc == "arib-std-b67":
        label = "Dolby Vision · HLG" if dolby_vision else "HDR · HLG"
        return ColorInfo(
            profile="hlg",
            label=label,
            confidence="high",
            hdr=True,
            dolby_vision=dolby_vision,
            reasons=reasons,
        )

    if any("apple log" in v.lower() or "applelog" in v.lower() for v in tag_values):
        return ColorInfo(
            profile="apple_log",
            label="Apple Log",
            confidence="high",
            log=True,
            reasons=[*reasons, "Apple Log tag"],
        )
    if depth >= 10 and trc in _UNSET and prim in _UNSET | {"bt2020"}:
        if apple:
            return ColorInfo(
                profile="apple_log",
                label="Apple Log",
                confidence="medium",
                log=True,
                reasons=[*reasons, "Apple camera, 10-bit, transfer not declared"],
            )
        return ColorInfo(
            profile="log_suspected",
            label="Log (taxminiy)",
            confidence="low",
            log=True,
            reasons=[*reasons, "10-bit, transfer not declared"],
        )

    if prim == "bt2020" and trc in _SDR_709_TRC | {"bt2020-10", "bt2020-12"}:
        return ColorInfo(profile="rec2020_sdr", label="Rec.2020 SDR", confidence="medium", reasons=reasons)
    if trc in _SDR_709_TRC or prim in _709_PRIMARIES:
        return ColorInfo(profile="rec709", label="Rec.709", confidence="high", reasons=reasons)
    if trc in _UNSET and depth <= 8:
        return ColorInfo(
            profile="rec709", label="Rec.709", confidence="low", reasons=[*reasons, "untagged 8-bit, assumed"]
        )
    return ColorInfo(profile="unknown", label="Noma'lum", confidence="low", reasons=reasons)
