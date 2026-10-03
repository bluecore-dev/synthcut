// Thin typed layer over Telegram's WebApp object (telegram-web-app.js).
// Outside Telegram the script still defines WebApp, but initData is empty —
// that is how we tell the two apart.

type HapticImpact = "light" | "medium" | "heavy" | "rigid" | "soft";

interface TelegramBackButton {
  show(): void;
  hide(): void;
  onClick(cb: () => void): void;
  offClick(cb: () => void): void;
}

export interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { user?: { id: number; first_name?: string; username?: string }; start_param?: string };
  version: string;
  platform: string;
  isVersionAtLeast(version: string): boolean;
  ready(): void;
  expand(): void;
  setHeaderColor(color: string): void;
  setBackgroundColor(color: string): void;
  setBottomBarColor?(color: string): void;
  enableClosingConfirmation(): void;
  disableClosingConfirmation(): void;
  disableVerticalSwipes?(): void;
  openTelegramLink(url: string): void;
  showConfirm?(message: string, callback: (ok: boolean) => void): void;
  downloadFile?(params: { url: string; file_name: string }, callback?: (accepted: boolean) => void): void;
  BackButton: TelegramBackButton;
  HapticFeedback: {
    impactOccurred(style: HapticImpact): void;
    notificationOccurred(type: "error" | "success" | "warning"): void;
    selectionChanged(): void;
  };
}

declare global {
  interface Window {
    Telegram?: { WebApp: TelegramWebApp };
  }
}

const raw = typeof window !== "undefined" ? window.Telegram?.WebApp : undefined;
export const tg: TelegramWebApp | null = raw && raw.initData ? raw : null;

export const BOT_USERNAME = "synthcut_bot";
const BG = "#0B0C0F";

function atLeast(version: string): boolean {
  try {
    return !!tg && tg.isVersionAtLeast(version);
  } catch {
    return false;
  }
}

export function initTelegram(): void {
  if (!tg) return;
  tg.ready();
  tg.expand();
  if (atLeast("6.1")) {
    tg.setHeaderColor(BG);
    tg.setBackgroundColor(BG);
  }
  if (atLeast("7.10")) tg.setBottomBarColor?.(BG);
  // Scrolling long lists must not swipe the Mini App closed mid-upload.
  if (atLeast("7.7")) tg.disableVerticalSwipes?.();
}

export const haptic = {
  tap: () => atLeast("6.1") && tg?.HapticFeedback.impactOccurred("light"),
  select: () => atLeast("6.1") && tg?.HapticFeedback.selectionChanged(),
  success: () => atLeast("6.1") && tg?.HapticFeedback.notificationOccurred("success"),
  warning: () => atLeast("6.1") && tg?.HapticFeedback.notificationOccurred("warning"),
  error: () => atLeast("6.1") && tg?.HapticFeedback.notificationOccurred("error"),
};

export function setClosingConfirmation(on: boolean): void {
  if (!atLeast("6.2")) return;
  if (on) tg?.enableClosingConfirmation();
  else tg?.disableClosingConfirmation();
}

export function confirmDialog(message: string): Promise<boolean> {
  if (tg?.showConfirm && atLeast("6.2")) {
    return new Promise((resolve) => tg!.showConfirm!(message, resolve));
  }
  return Promise.resolve(window.confirm(message));
}

export function backButton(): TelegramBackButton | null {
  return atLeast("6.1") && tg ? tg.BackButton : null;
}

/** Project id passed by the bot's "open project" button (?p=<uuid>). */
export function launchProjectId(): string | null {
  const p = new URLSearchParams(window.location.search).get("p");
  return p && /^[0-9a-f-]{36}$/i.test(p) ? p : null;
}

/** Telegram 8.0+ saves files natively; elsewhere the presigned link (Content-Disposition: attachment) does it. */
export function downloadFile(url: string, fileName: string): void {
  if (tg?.downloadFile && tg.isVersionAtLeast("8.0")) {
    tg.downloadFile({ url, file_name: fileName });
    return;
  }
  window.open(url, "_blank", "noopener");
}
