import { Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { LogoRevealProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { READABLE } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

export function LogoReveal({ props, durationInFrames }: WidgetProps<LogoRevealProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, assets } = useTheme();
  const { vmin } = useUnits();
  const accent = accentOf(props, theme);
  const image = props.image_asset_id ? assets[props.image_asset_id] : undefined;
  const p = spring({ frame, fps, config: { damping: 14, stiffness: 120 }, durationInFrames: Math.round(0.9 * fps) });
  const tag = interpolate(frame, [fps * 0.6, fps * 1.0], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const glitch = props.style === "glitch" && frame < fps * 0.7 ? Math.sin(frame * 2.3) * vmin * 0.8 : 0;
  const scale = props.style === "scale" ? 0.6 + 0.4 * p : 1;
  const opacity = props.style === "fade" ? p : Math.min(1, p * 1.5);
  const word = (
    <div style={{ fontFamily: FONT_STACK("Montserrat"), fontWeight: 900, fontSize: vmin * 11, letterSpacing: "-0.02em", color: "#fff", textShadow: READABLE, position: "relative" }}>
      {glitch !== 0 && <span style={{ position: "absolute", left: glitch, color: accent, opacity: 0.7, mixBlendMode: "screen" }}>{props.text}</span>}
      {glitch !== 0 && <span style={{ position: "absolute", left: -glitch, color: "#FF2D55", opacity: 0.7, mixBlendMode: "screen" }}>{props.text}</span>}
      <span style={{ position: "relative" }}>{props.text}</span>
    </div>
  );
  return (
    <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Animated enter={props.enter === "pop" ? "none" : props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", opacity, transform: `scale(${scale})` }}>
          {image ? <Img src={image} style={{ maxWidth: vmin * 40, maxHeight: vmin * 24, objectFit: "contain" }} /> : word}
          <div style={{ marginTop: vmin * 1.6, height: vmin * 0.6, width: vmin * 30 * p, background: accent, borderRadius: vmin }} />
          {props.tagline && <div style={{ marginTop: vmin * 1.6, fontFamily: FONT_STACK("Inter"), fontWeight: 500, fontSize: vmin * 3.2, color: "#fff", opacity: tag, letterSpacing: "0.08em", textTransform: "uppercase", textShadow: READABLE }}>{props.tagline}</div>}
        </div>
      </Animated>
    </div>
  );
}
