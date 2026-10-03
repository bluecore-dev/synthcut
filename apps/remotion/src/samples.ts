// Sample props: Studio previews of every widget and the smoke-render test.
import type { CaptionLine, ComponentProps, OverlayProps } from "./generated/types";
import type { ComponentName } from "./widgets";

const base = { enter: "pop", exit: "fade", accent: null } as const;

export const WIDGET_SAMPLES: ComponentProps = {
  GamifiedTimer: { ...base, total_seconds: 5, label: "Javob bering!", warn_at: 3, position: "top_right" },
  QuizCard: { ...base, question: "O'zbekiston poytaxti qaysi shahar?", options: ["Samarqand", "Toshkent", "Buxoro"], correct_index: 1, reveal_at: 2.2 },
  AbacusWidget: { ...base, value: 2026, rods: 5, from_value: 0, position: "center" },
  DocumentCard: { ...base, title: "Shartnoma №42", subtitle: "Bluecore × Mijoz", lines: ["Muddat: 14 kun", "To'lov: 40 / 60", "Kafolat: 3 oy"], image_asset_id: null },
  ScoreCounter: { ...base, to_value: 12500, from_value: 0, decimals: 0, prefix: "", suffix: "+", label: "obunachi", position: "center" },
  AnimatedSubtitle: { ...base, text: "Raqamlardan boshlaymiz: o‘sish 3 barobar", highlight: ["3", "barobar"], position: "center" },
  TitleCard: { ...base, title: "Omonjon", subtitle: "Bluecore asoschisi", variant: "lower_third" },
  CTA: { ...base, text: "Obuna bo'ling", action: "subscribe", handle: "@bluecore", position: "bottom" },
  LogoReveal: { ...base, text: "BlueCore", tagline: "IT agency", image_asset_id: null, style: "glitch" },
  ProgressBar: { ...base, enter: "fade", chapters: [{ title: "Kirish", at: 0 }, { title: "Asosiy qism", at: 1.5 }, { title: "Xulosa", at: 3.5 }], position: "top" },
  Chart: { ...base, kind: "bar", title: "Oylik sotuv", series: [{ label: "Yan", value: 12 }, { label: "Fev", value: 18 }, { label: "Mar", value: 27 }], unit: "M" },
  PhoneMockup: { ...base, image_asset_id: null, caption: "Mini App ichida", position: "center" },
  Notification: { ...base, enter: "slide_left", app: "Telegram", title: "Yangi buyurtma", body: "Osh-Posh: 2 × palov, yetkazib berish 19:30", icon: "telegram" },
  Highlight: { ...base, region: { x: 0.3, y: 0.35, width: 0.4, height: 0.2 }, shape: "box" },
  Callout: { ...base, target: { x: 0.55, y: 0.55 }, text: "Mana shu yerda", side: "right" },
};

const SAMPLE_LINES: CaptionLine[] = [
  { start: 0.2, end: 1.4, words: [{ text: "Assalomu", start: 0.2, end: 0.7 }, { text: "alaykum,", start: 0.75, end: 1.3 }] },
  { start: 1.5, end: 2.9, words: [{ text: "bugun", start: 1.5, end: 1.8 }, { text: "o‘zbek", start: 1.85, end: 2.2 }, { text: "tili", start: 2.25, end: 2.5 }, { text: "haqida.", start: 2.55, end: 2.9 }] },
  { start: 3.0, end: 4.6, words: [{ text: "Қадрли", start: 3.0, end: 3.5 }, { text: "дўстлар!", start: 3.55, end: 4.2 }] },
];

const frame = (width: number, height: number) =>
  height > width ? { top: 0.1, bottom: 0.22, left: 0.06, right: 0.14 } : { top: 0.06, bottom: 0.08, left: 0.06, right: 0.06 };

export function sampleOverlay(width = 1080, height = 1920, fps = 30): OverlayProps {
  return {
    schema_version: "overlay/1",
    width,
    height,
    fps,
    duration_in_frames: 5 * fps,
    safe_zone: frame(width, height),
    theme: { primary: "#1A4F8A", accent: "#00C4FF", text: "#FFFFFF", highlight: "#FFD60A", font: "Montserrat" },
    items: [],
    captions: { style: "dynamic", position: "bottom", lines: SAMPLE_LINES },
    assets: {},
  };
}

export function widgetOverlay(name: ComponentName, width = 1080, height = 1920, fps = 30): OverlayProps {
  return {
    ...sampleOverlay(width, height, fps),
    captions: null,
    items: [{ id: "sample", component: name, from_frame: 0, duration_frames: 5 * fps, layer: 1, props: WIDGET_SAMPLES[name] as unknown as Record<string, unknown> }],
  };
}
