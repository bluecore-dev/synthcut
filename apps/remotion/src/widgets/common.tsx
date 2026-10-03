import type { CSSProperties, ReactNode } from "react";
import { FONT_STACK } from "../lib/theme";

export type WidgetProps<P> = { props: P; durationInFrames: number };

/** The shared look: dark glass card with a soft shadow, readable on any footage. */
export function cardStyle(vmin: number, extra?: CSSProperties): CSSProperties {
  return {
    background: "rgba(12, 18, 32, 0.86)",
    border: `${Math.max(1, vmin * 0.15)}px solid rgba(255,255,255,0.12)`,
    borderRadius: vmin * 2.4,
    boxShadow: `0 ${vmin * 1.2}px ${vmin * 4}px rgba(0,0,0,0.45)`,
    color: "#fff",
    fontFamily: FONT_STACK("Montserrat"),
    ...extra,
  };
}

const PATHS: Record<string, ReactNode> = {
  bell: <path d="M12 3a6 6 0 0 0-6 6v3.6L4.3 15.4A1 1 0 0 0 5.2 17h13.6a1 1 0 0 0 .9-1.6L18 12.6V9a6 6 0 0 0-6-6Zm0 19a3 3 0 0 0 3-3H9a3 3 0 0 0 3 3Z" />,
  heart: <path d="M12 21s-7.5-4.6-9.5-9.2C1 8.3 3.2 5 6.6 5c2 0 3.6 1.1 5.4 3 1.8-1.9 3.4-3 5.4-3 3.4 0 5.6 3.3 4.1 6.8C19.5 16.4 12 21 12 21Z" />,
  comment: <path d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z" />,
  link: <path d="M10.6 13.4a1 1 0 0 0 1.4 1.4l4-4a3 3 0 0 0-4.2-4.2l-1.5 1.5 1.4 1.4 1.5-1.5a1 1 0 0 1 1.4 1.4l-4 4ZM13.4 10.6a1 1 0 0 0-1.4-1.4l-4 4a3 3 0 0 0 4.2 4.2l1.5-1.5-1.4-1.4-1.5 1.5a1 1 0 0 1-1.4-1.4l4-4Z" />,
  telegram: <path d="M21.5 3.6 2.9 10.8c-1.3.5-1.3 1.2-.2 1.6l4.8 1.5 1.8 5.6c.2.6.1.8.7.8.5 0 .7-.2 1-.5l2.4-2.3 4.9 3.6c.9.5 1.5.2 1.8-.8L23 5c.3-1.4-.5-2-1.5-1.4ZM8.3 13.6l9.6-6c.5-.3.9-.1.5.2l-8.2 7.4-.3 3.4-1.6-5Z" />,
  instagram: <path d="M7 2h10a5 5 0 0 1 5 5v10a5 5 0 0 1-5 5H7a5 5 0 0 1-5-5V7a5 5 0 0 1 5-5Zm5 5a5 5 0 1 0 0 10 5 5 0 0 0 0-10Zm0 2a3 3 0 1 1 0 6 3 3 0 0 1 0-6Zm5.5-3.2a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4Z" />,
  message: <path d="M4 4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-6l-5 4v-4H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Zm3 5v2h10V9H7Zm0 3v2h6v-2H7Z" />,
  check: <path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4L9 16.2Z" />,
};

export function Icon({ name, size, color = "currentColor" }: { name: keyof typeof PATHS | string; size: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill={color} style={{ flexShrink: 0 }}>
      {PATHS[name] ?? PATHS.bell}
    </svg>
  );
}

export function formatNumber(value: number, decimals: number): string {
  return value.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).replace(/,/g, " ");
}
