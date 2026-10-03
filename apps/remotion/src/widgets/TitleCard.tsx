import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { TitleCardProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { READABLE } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

export function TitleCard({ props, durationInFrames }: WidgetProps<TitleCardProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin, portrait } = useUnits();
  const accent = accentOf(props, theme);
  const bar = spring({ frame, fps, config: { damping: 18 }, durationInFrames: Math.round(0.5 * fps) });
  const sub = interpolate(frame, [fps * 0.25, fps * 0.55], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  if (props.variant === "lower_third") {
    return (
      <div style={{ position: "absolute", left: safe.left * width, bottom: safe.bottom * height + vmin * (portrait ? 14 : 4) }}>
        <Animated enter={props.enter === "pop" ? "slide_left" : props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
          <div style={{ display: "flex", alignItems: "stretch", fontFamily: FONT_STACK("Montserrat") }}>
            <div style={{ width: vmin * 1.2, background: accent, transform: `scaleY(${bar})`, transformOrigin: "bottom" }} />
            <div style={{ background: "rgba(12,18,32,0.85)", padding: `${vmin * 1.4}px ${vmin * 2.6}px`, clipPath: `inset(0 ${(1 - bar) * 100}% 0 0)` }}>
              <div style={{ fontWeight: 800, fontSize: vmin * 4.2, color: "#fff", whiteSpace: "nowrap" }}>{props.title}</div>
              {props.subtitle && <div style={{ fontWeight: 600, fontSize: vmin * 2.6, color: accent, opacity: sub, marginTop: vmin * 0.4 }}>{props.subtitle}</div>}
            </div>
          </div>
        </Animated>
      </div>
    );
  }
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: `0 ${safe.left * width}px` }}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin} style={{ textAlign: "center" }}>
        <div style={{ fontFamily: FONT_STACK("Montserrat"), fontWeight: 900, fontSize: vmin * (portrait ? 9 : 8), color: "#fff", lineHeight: 1.08, textShadow: READABLE }}>{props.title}</div>
        <div style={{ margin: `${vmin * 2}px auto`, height: vmin * 0.9, width: `${bar * 30}%`, background: accent, borderRadius: vmin }} />
        {props.subtitle && <div style={{ fontFamily: FONT_STACK("Inter"), fontWeight: 500, fontSize: vmin * 3.6, color: "#fff", opacity: sub, textShadow: READABLE }}>{props.subtitle}</div>}
      </Animated>
    </div>
  );
}
