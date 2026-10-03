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

export const PROJECT_TABS = [
  { id: "overview", label: "Overview", phase: 1 },
  { id: "assets", label: "Assets", phase: 2 },
  { id: "logs", label: "Logs", phase: 1 },
  { id: "analysis", label: "Analysis", phase: 5 },
  { id: "transcript", label: "Transcript", phase: 4 },
  { id: "timeline", label: "Timeline", phase: 6 },
  { id: "decisions", label: "AI Decisions", phase: 6 },
  { id: "preview", label: "Preview", phase: 11 },
  { id: "versions", label: "Versions", phase: 6 },
  { id: "renders", label: "Render History", phase: 11 },
] as const;

export type ProjectTab = (typeof PROJECT_TABS)[number]["id"];

export const UPLOAD_HINT_IOS =
  "iPhone'da Log/ProRes asli kerak bo'lsa, faylni «Fayllar» (Files) ilovasidan tanlang — «Rasmlar» videoni siqib yuborishi mumkin.";
