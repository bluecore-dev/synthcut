import { useCurrentFrame, useVideoConfig } from "remotion";
import type { ProgressBarProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { READABLE } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

export function ProgressBar({ props, durationInFrames }: WidgetProps<ProgressBarProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin } = useUnits();
  const accent = accentOf(props, theme);
  const total = durationInFrames / fps;
  const t = frame / fps;
  const progress = Math.min(1, frame / durationInFrames);
  const current = [...props.chapters].reverse().find((c) => c.at <= t);
  const edge = props.position === "top" ? { top: safe.top * height * 0.5 } : { bottom: safe.bottom * height * 0.5 };
  return (
    <div style={{ position: "absolute", left: safe.left * width, right: safe.right * width, ...edge }}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        {current && <div style={{ marginBottom: vmin * 0.8, fontFamily: FONT_STACK("Montserrat"), fontWeight: 800, fontSize: vmin * 2.6, color: "#fff", textShadow: READABLE }}>{current.title}</div>}
        <div style={{ position: "relative", height: vmin * 1.1, borderRadius: vmin, background: "rgba(255,255,255,0.25)", overflow: "hidden" }}>
          <div style={{ position: "absolute", inset: 0, width: `${progress * 100}%`, background: accent, borderRadius: vmin }} />
          {props.chapters.map((c, i) => (
            <div key={i} style={{ position: "absolute", top: 0, bottom: 0, left: `${(c.at / total) * 100}%`, width: Math.max(2, vmin * 0.35), background: "rgba(0,0,0,0.55)" }} />
          ))}
        </div>
      </Animated>
    </div>
  );
}
