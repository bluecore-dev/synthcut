import type { Schemas } from "./api/client";

type Mode = Schemas["ProjectMode"];
type Language = Schemas["ProjectLanguage"];
type StageStatus = Schemas["StageStatus"];
type AssetStatus = Schemas["AssetStatus"];

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
