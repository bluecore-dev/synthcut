import { createContext, useContext, type ReactNode } from "react";
import { useVideoConfig } from "remotion";
import type { SafeZone, Theme } from "../generated/types";

type Ctx = { theme: Theme; safe: SafeZone; assets: Record<string, string> };

const DEFAULT: Ctx = {
  theme: { primary: "#1A4F8A", accent: "#00C4FF", text: "#FFFFFF", highlight: "#FFD60A", font: "Montserrat" },
  safe: { top: 0.06, bottom: 0.08, left: 0.06, right: 0.06 },
  assets: {},
};

const ThemeContext = createContext<Ctx>(DEFAULT);

export function ThemeProvider({ value, children }: { value: Ctx; children: ReactNode }) {
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

/** Sizes scale with the frame, so a layout designed once works at 720p and 4K, 9:16 and 16:9. */
export function useUnits() {
  const { width, height } = useVideoConfig();
  const vmin = Math.min(width, height) / 100;
  return { width, height, vmin, portrait: height > width };
}

export const accentOf = (props: { accent: string | null }, theme: Theme) => props.accent ?? theme.accent;

export const FONT_STACK = (font: string) => `"${font}", "Inter", system-ui, sans-serif`;
