"""FFprobe → MediaInfo (spec §9 MEDIA METADATA)."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from typing import Any

from .color import classify_color
from .errors import MediaError
from .models import AudioStream, MediaInfo, MediaKind, VideoStream

IMAGE_CODECS = {"mjpeg", "png", "bmp", "tiff", "webp", "gif", "hevc_image", "jpegxl", "heif"}
_CAMERA_KEYS = {
    "com.apple.quicktime.make": "make",
    "make": "make",
    "com.apple.quicktime.model": "model",
    "model": "model",
    "com.apple.quicktime.software": "software",
    "com.apple.quicktime.creationdate": "created",
    "creation_time": "created",
    "com.apple.quicktime.camera.lens_model": "lens",
    "com.android.manufacturer": "make",
    "com.android.model": "model",
    "com.android.version": "software",
}


def run_ffprobe(source: str, *, timeout: int = 120, binary: str = "ffprobe") -> dict[str, Any]:
    args = [
        binary,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        source,
    ]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise MediaError("ffprobe javob bermadi (timeout)", permanent=False) from exc
    if out.returncode != 0:
        detail = out.stderr.strip().splitlines()[-1:] or ["ffprobe failed"]
        permanent = any(
            m in out.stderr for m in ("Invalid data", "moov atom not found", "could not find codec")
        )
        raise MediaError(f"Fayl o'qilmadi: {detail[0][:200]}", permanent=permanent)
    try:
        return json.loads(out.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe noto'g'ri JSON qaytardi", permanent=False) from exc


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _rate(value: Any) -> float | None:
    try:
        frac = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return float(frac) if frac > 0 else None


def _bit_depth(stream: dict[str, Any]) -> int | None:
    depth = _int(stream.get("bits_per_raw_sample"))
    if depth:
        return depth
    fmt = str(stream.get("pix_fmt") or "")
    for marker, value in (("16", 16), ("14", 14), ("12", 12), ("10", 10), ("p9", 9)):
        if marker in fmt:
            return value
    return 8 if fmt else None


def _chroma(pix_fmt: str | None) -> str | None:
    fmt = pix_fmt or ""
    if "444" in fmt or fmt.startswith(("rgb", "bgr", "gbr")):
        return "444"
    if "422" in fmt:
        return "422"
    if "420" in fmt or fmt.startswith(("nv12", "p010", "yuvj420")):
        return "420"
    return None


def _rotation(stream: dict[str, Any]) -> int:
    rot: float | None = None
    for item in stream.get("side_data_list") or []:
        if "rotation" in item:
            rot = _float(item.get("rotation"))
    if rot is None:
        rot = _float((stream.get("tags") or {}).get("rotate"))
    if rot is None:
        return 0
    return round(rot) % 360 // 90 * 90


def _dolby_vision(stream: dict[str, Any]) -> bool:
    return any(
        "dovi" in str(item.get("side_data_type", "")).lower() for item in stream.get("side_data_list") or []
    )


def _video(stream: dict[str, Any]) -> VideoStream:
    width = _int(stream.get("width")) or 0
    height = _int(stream.get("height")) or 0
    disp_w, disp_h = width, height
    sar = str(stream.get("sample_aspect_ratio") or "1:1")
    try:
        num, den = (int(x) for x in sar.split(":"))
        if num > 0 and den > 0 and num != den:
            disp_w = round(width * num / den)
    except ValueError:
        pass
    rotation = _rotation(stream)
    if rotation in (90, 270):
        disp_w, disp_h = disp_h, disp_w
    avg = _rate(stream.get("avg_frame_rate"))
    real = _rate(stream.get("r_frame_rate"))
    fps = avg or real
    # 30000/1001 vs 2997/100 is the same rate; 29.97 average vs 30 nominal is a VFR phone clip.
    vfr = bool(avg and real and abs(avg - real) / real > 0.0005)
    pix_fmt = stream.get("pix_fmt")
    return VideoStream(
        codec=stream.get("codec_name"),
        profile=stream.get("profile"),
        width=width,
        height=height,
        display_width=disp_w,
        display_height=disp_h,
        rotation=rotation,
        fps=round(fps, 3) if fps else None,
        vfr=vfr,
        pix_fmt=pix_fmt,
        bit_depth=_bit_depth(stream),
        chroma=_chroma(pix_fmt),
        bitrate=_int(stream.get("bit_rate")),
        frames=_int(stream.get("nb_frames")),
        color_range=stream.get("color_range"),
        color_primaries=stream.get("color_primaries"),
        color_transfer=stream.get("color_transfer"),
        color_space=stream.get("color_space"),
    )


def _audio(stream: dict[str, Any]) -> AudioStream:
    return AudioStream(
        codec=stream.get("codec_name"),
        profile=stream.get("profile"),
        channels=_int(stream.get("channels")),
        channel_layout=stream.get("channel_layout"),
        sample_rate=_int(stream.get("sample_rate")),
        bitrate=_int(stream.get("bit_rate")),
        bit_depth=_int(stream.get("bits_per_raw_sample")) or _int(stream.get("bits_per_sample")) or None,
    )


def normalize(raw: dict[str, Any], *, size_bytes: int) -> MediaInfo:
    fmt = raw.get("format") or {}
    streams = raw.get("streams") or []
    videos = [
        s
        for s in streams
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")
    ]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    format_name = str(fmt.get("format_name") or "")
    duration = _float(fmt.get("duration"))
    if duration is None and videos:
        duration = _float(videos[0].get("duration"))
    if duration is None and audios:
        duration = _float(audios[0].get("duration"))

    video_raw = videos[0] if videos else None
    is_image = bool(
        video_raw
        and (
            "image2" in format_name
            or format_name.endswith("_pipe")
            or (video_raw.get("codec_name") in IMAGE_CODECS and (duration is None or duration < 0.05))
        )
    )
    kind: MediaKind
    if video_raw is not None:
        kind = "image" if is_image else "video"
    elif audios:
        kind = "audio"
    else:
        kind = "other"

    tags = {str(k).lower(): str(v) for k, v in (fmt.get("tags") or {}).items()}
    for s in streams:
        for k, v in (s.get("tags") or {}).items():
            tags.setdefault(str(k).lower(), str(v))
    camera: dict[str, str] = {}
    for key, name in _CAMERA_KEYS.items():
        if key in tags and name not in camera:
            camera[name] = tags[key][:120]
    has_location = any("location" in k or k in ("gps", "xyz") for k in tags)

    video = _video(video_raw) if video_raw is not None else None
    color = classify_color(
        video,
        is_image=is_image,
        make=camera.get("make"),
        tag_values=list(tags.values()),
        dolby_vision=bool(video_raw and _dolby_vision(video_raw)),
    )
    return MediaInfo(
        kind=kind,
        container=format_name or None,
        duration=round(duration, 3) if duration is not None and kind != "image" else None,
        size_bytes=size_bytes,
        bitrate=_int(fmt.get("bit_rate")),
        video=video,
        audio=_audio(audios[0]) if audios else None,
        audio_streams=len(audios),
        color=color,
        camera=camera,
        has_location=has_location,
    )
