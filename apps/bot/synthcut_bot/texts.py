"""Bot texts (Uzbek) and formatting of project state for chat."""

from __future__ import annotations

from html import escape

from synthcut_schemas.api import ProjectOut, ProjectSummary
from synthcut_schemas.enums import PRESET_SPECS, STAGE_LABELS, StageStatus

STATUS_ICON = {
    StageStatus.DONE: "✅",
    StageStatus.RUNNING: "🔵",
    StageStatus.QUEUED: "⏳",
    StageStatus.WAITING_USER: "✋",
    StageStatus.FAILED: "❌",
    StageStatus.SKIPPED: "➖",
    StageStatus.BLOCKED: "⛔",
    StageStatus.PENDING: "▫️",
}

WELCOME = (
    "🎬 <b>SynthCut</b> — AI post-production tizimi.\n\n"
    "Loyiha yarating, xom videolarni yuklang — tahlil, montaj, rang, ovoz, grafika va render'ni "
    "agentlar jamoasi bajaradi.\n\n"
    "Asosiy ish Mini App ichida: pastdagi tugma orqali oching.\n\n"
    "Buyruqlar:\n"
    "/new <i>nom</i> — yangi loyiha\n"
    "/projects — loyihalar ro'yxati\n"
    "/status — oxirgi loyiha holati\n"
    "/montaj — oxirgi loyihani Tez montaj qilib, videoni shu yerga olish\n"
    "/help — yordam"
)

HELP = (
    "<b>SynthCut buyruqlari</b>\n\n"
    "/new <i>nom</i> — yangi loyiha (masalan: <code>/new Kuzgi reel</code>)\n"
    "/projects — oxirgi loyihalar\n"
    "/status — oxirgi loyihaning pipeline holati\n"
    "/montaj — oxirgi loyihani Tez montaj: pauzalar kesiladi, rang, ovoz, subtitr — tayyor video shu chatga keladi\n\n"
    "Videolar Mini App orqali to'g'ridan-to'g'ri saqlash tizimiga yuklanadi — bot orqali emas. "
    "Katta fayllar (4–50 GB) uzilsa ham davom ettiriladi."
)

NEW_USAGE = "Loyiha nomini yozing: <code>/new Mening reelim</code>"
NO_PROJECTS = "Hali loyiha yo'q. <code>/new Nom</code> bilan yarating yoki Mini App'ni oching."
OPEN_APP = "🎬 SynthCut'ni ochish"
OPEN_PROJECT = "📂 Loyihani ochish"
HTTPS_REQUIRED = "\n\n<i>Mini App tugmasi faqat HTTPS manzilda ishlaydi.</i>"


def denied(telegram_id: int) -> str:
    return (
        "⛔ <b>Bu xususiy tizim.</b>\n\n"
        f"Sizning Telegram ID: <code>{telegram_id}</code>\n"
        "Kirish uchun tizim egasi bu ID'ni ruxsat ro'yxatiga qo'shishi kerak."
    )


def _gb(n: int) -> str:
    return f"{n / 1024**3:.2f} GB"


def project_line(p: ProjectSummary) -> str:
    spec = PRESET_SPECS[p.preset]
    stage = f" · {STAGE_LABELS[p.active_stage]}" if p.active_stage else ""
    return (
        f"🎞 <b>{escape(p.name)}</b>\n"
        f"    {spec.aspect} · {p.asset_count} ta fayl · {_gb(p.total_bytes)} · {round(p.progress * 100)}%{stage}"
    )


def project_created(p: ProjectOut) -> str:
    spec = PRESET_SPECS[p.preset]
    return (
        f"✅ Loyiha yaratildi: <b>{escape(p.name)}</b>\n"
        f"{spec.label} · {spec.width}×{spec.height} · {p.fps} fps · {p.mode.value}\n\n"
        "Endi Mini App'da videolarni yuklang."
    )


def project_status(p: ProjectOut) -> str:
    spec = PRESET_SPECS[p.preset]
    lines = [
        f"🎬 <b>{escape(p.name)}</b>",
        f"{spec.label} · {spec.width}×{spec.height} · {p.fps} fps · {p.mode.value}",
        f"📁 {p.asset_count} ta fayl · {_gb(p.total_bytes)}",
        f"📊 Progress: {round(p.progress * 100)}%",
        "",
    ]
    for st in p.stages:
        suffix = f" — {escape(st.detail)}" if st.detail else ""
        later = "" if st.available else f" <i>(Phase {st.phase})</i>"
        lines.append(f"{STATUS_ICON[st.status]} {st.label}{suffix}{later}")
    return "\n".join(lines)


def montaj_reply(project_name: str, started) -> str:
    """``started`` is ``synthcut_core.renders.AutoEditStart``."""
    head = f"✂️ <b>{escape(project_name, quote=False)}</b>\n"
    if started.refused is not None:
        return head + escape(started.refused[1], quote=False)
    if not started.created:
        return head + "Tez montaj allaqachon jarayonda — natijani Mini App'da kuzating."
    return head + (
        "Tez montaj boshlandi: pauzalar kesiladi, rang va ovoz tuzatiladi, subtitr qo'yiladi, "
        "keyin asl fayllardan render va sifat nazorati.\n"
        "Tayyor video shu chatga keladi — odatda video uzunligiga qarab 10–30 daqiqa. "
        "Sozlamalar oxirgi tanlovlaringiz va fikrlaringizdan olinadi."
    )
