import type { Schemas } from "./api/client";

type Mode = Schemas["ProjectMode"];
type Language = Schemas["ProjectLanguage"];
type StageStatus = Schemas["StageStatus"];
type AssetStatus = Schemas["AssetStatus"];
type TranscriptStatus = Schemas["TranscriptStatus"];
type AnalysisStatus = Schemas["AnalysisStatus"];
type Clip = Schemas["ClipOut"];

export const MODE_LABEL: Record<Mode, { title: string; hint: string }> = {
  auto: { title: "Auto", hint: "AI to'liq mustaqil ishlaydi" },
  assisted: { title: "Assisted", hint: "Muhim qarorlardan oldin so'raydi" },
  manual: { title: "Manual", hint: "Timeline va reja sizning nazoratingizda" },
};

export const LANGUAGE_LABEL: Record<Language, string> = {
  auto: "Avto",
  uz: "O'zbek",
  ru: "Русский",
  en: "English",
};

export const STAGE_STATUS_LABEL: Record<StageStatus, string> = {
  pending: "kutilmoqda",
  queued: "navbatda",
  running: "ishlamoqda",
  done: "tayyor",
  failed: "xato",
  skipped: "o'tkazildi",
  blocked: "to'silgan",
  waiting_user: "sizni kutmoqda",
};

export const ASSET_STATUS_LABEL: Record<AssetStatus, string> = {
  uploading: "yuklanmoqda",
  uploaded: "yuklandi",
  ingesting: "tahlil qilinmoqda",
  ready: "tayyor",
  failed: "xato",
  cancelled: "bekor qilindi",
};

export const TRANSCRIPT_STATUS_LABEL: Record<TranscriptStatus, string> = {
  queued: "navbatda",
  running: "matnga o'girilmoqda",
  done: "tayyor",
  failed: "xato",
};

export const ANALYSIS_STATUS_LABEL: Record<AnalysisStatus, string> = {
  queued: "navbatda",
  running: "tahlil qilinmoqda",
  done: "tayyor",
  failed: "xato",
};

export const SHOT_TYPE_LABEL: Record<Clip["shot_type"], string> = {
  close_up: "Yaqin plan",
  medium: "O'rta plan",
  wide: "Umumiy plan",
  unknown: "Odamsiz",
};

export const CAMERA_MOTION_LABEL: Record<Clip["camera_motion"], string> = {
  static: "Statik",
  pan_left: "Chapga panorama",
  pan_right: "O'ngga panorama",
  tilt_up: "Yuqoriga",
  tilt_down: "Pastga",
  handheld: "Qo'lda",
  moving: "Harakatli",
};

export const CLIP_FLAG_LABEL: Record<Clip["flags"][number], string> = {
  black: "qora kadr",
  blurry: "xira",
  underexposed: "qorong'i",
  overexposed: "o'ta yorug'",
  shaky: "silkingan",
  frozen: "qotib qolgan",
  too_short: "juda qisqa",
  duplicate: "takror",
};

export const CAPTION_STYLE_LABEL: Record<"dynamic" | "karaoke" | "minimal" | "bold", { title: string; hint: string }> = {
  dynamic: { title: "Dinamik", hint: "So'zlar aytilishi bilan chiqadi, joriy so'z ajraladi" },
  karaoke: { title: "Karaoke", hint: "Butun qator ko'rinadi, aytilgan qism bo'yaladi" },
  minimal: { title: "Oddiy", hint: "Klassik subtitr, qora fon ustida" },
  bold: { title: "Qalin", hint: "Katta harflar, joriy so'z belgi ostida" },
};

export const CAPTION_POSITION_LABEL: Record<"bottom" | "center" | "top", string> = { bottom: "Pastda", center: "Markazda", top: "Tepada" };

export const ENHANCE_PROFILE_LABEL: Record<"neutral" | "cinematic_clean" | "warm_film" | "cool_teal" | "vivid_social" | "bw_classic", { title: string; hint: string }> = {
  neutral: { title: "Tabiiy", hint: "Faqat ekspozitsiya va oq balans tuzatiladi" },
  cinematic_clean: { title: "Kino", hint: "Moviy soyalar, iliq teri ranglari" },
  warm_film: { title: "Iliq plyonka", hint: "Yumshoq, iliq, ko'tarilgan qora" },
  cool_teal: { title: "Sovuq", hint: "Zamonaviy moviy tus, kontrastli" },
  vivid_social: { title: "Yorqin", hint: "Telefon ekrani uchun to'yingan ranglar" },
  bw_classic: { title: "Oq-qora", hint: "Klassik kontrastli oq-qora" },
};

export const LOUDNESS_TARGET_LABEL: Record<"social" | "youtube" | "podcast" | "broadcast", string> = {
  social: "Ijtimoiy tarmoq · −14",
  youtube: "YouTube · −14",
  podcast: "Podkast · −16",
  broadcast: "TV · −23",
};

export const SUBJECT_LABEL: Record<string, string> = { person: "1 kishi", people: "bir necha kishi", crowd: "olomon" };

/** Whisper language codes we can name; anything else is shown as the code. */
export const SPEECH_LANGUAGE_NAME: Record<string, string> = {
  uz: "O'zbek",
  ru: "Русский",
  en: "English",
  kk: "Qozoq",
  ky: "Qirg'iz",
  tg: "Tojik",
  tk: "Turkman",
  tr: "Turk",
  az: "Ozarbayjon",
};

export const SHORT_DURATIONS = [30, 45, 60, 90, 120];
export const LONG_DURATIONS = [300, 600, 900];

/** ``stage``: the tab opens when the server says that stage is built. */
export const PROJECT_TABS = [
  { id: "overview", label: "Overview" },
  { id: "assets", label: "Assets" },
  { id: "logs", label: "Logs" },
  { id: "analysis", label: "Analysis", stage: "analysis" },
  { id: "transcript", label: "Transcript", stage: "transcription" },
  { id: "timeline", label: "Timeline", stage: "editor" },
  { id: "decisions", label: "AI Decisions", stage: "director" },
  { id: "preview", label: "Preview", stage: "render" },
  { id: "versions", label: "Versions", stage: "editor" },
  { id: "renders", label: "Render History", stage: "render" },
] as const satisfies readonly { id: string; label: string; stage?: string }[];

export type ProjectTab = (typeof PROJECT_TABS)[number]["id"];

export const UPLOAD_HINT_IOS =
  "iPhone'da Log/ProRes asli kerak bo'lsa, faylni «Fayllar» (Files) ilovasidan tanlang — «Rasmlar» videoni siqib yuborishi mumkin.";

export const QA_LABEL: Record<"pass" | "warn" | "fail", { title: string; tone: "ok" | "warn" | "err" }> = {
  pass: { title: "QA: joyida", tone: "ok" },
  warn: { title: "QA: ogohlantirish", tone: "warn" },
  fail: { title: "QA: xato", tone: "err" },
};

export const DELIVERY_LABEL: Record<"none" | "queued" | "sent" | "failed", string> = {
  none: "Yuborilmagan",
  queued: "Telegramga yuborilmoqda",
  sent: "Telegramga yuborildi",
  failed: "Telegramga yuborilmadi",
};

export const PLAN_SOURCE_LABEL: Record<"rules" | "director" | "user", string> = {
  rules: "Tez montaj",
  director: "AI rejissor",
  user: "Qo'lda",
};

/** Target length chips for Tez montaj; null = keep everything usable. */
export const AUTO_EDIT_DURATIONS: (number | null)[] = [null, 15, 30, 60, 90];
