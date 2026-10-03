import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { AnimatedSubtitleProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place, READABLE } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

/** A hand-placed line (titles, quotes) revealed word by word across its duration. */
export function AnimatedSubtitle({ props, durationInFrames }: WidgetProps<AnimatedSubtitleProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin, portrait } = useUnits();
  const words = props.text.split(/\s+/).filter(Boolean);
  const highlight = new Set(props.highlight.map((w) => w.toLowerCase()));
  const span = Math.max(1, Math.min(durationInFrames * 0.6, words.length * fps * 0.25));
  return (
    <div style={place(props.position, safe, width, height)}>
      <Animated enter={props.enter === "pop" ? "none" : props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={{ textAlign: "center", fontFamily: FONT_STACK("Montserrat"), fontWeight: 800, fontSize: vmin * (portrait ? 7 : 5.6), color: "#fff", textShadow: READABLE, lineHeight: 1.2 }}>
          {words.map((w, i) => {
            const p = spring({ frame: frame - Math.round((i / words.length) * span), fps, config: { damping: 13, stiffness: 210, mass: 0.5 }, durationInFrames: Math.round(0.3 * fps) });
            const hot = highlight.has(w.toLowerCase().replace(/[^\p{L}\p{N}'‘’]/gu, ""));
            return (
              <span key={i} style={{ display: "inline-block", opacity: p, transform: `translateY(${(1 - p) * vmin * 3}px) scale(${0.8 + 0.2 * p})`, color: hot ? accentOf(props, theme) : undefined, marginRight: "0.28em" }}>
                {w}
              </span>
            );
          })}
        </div>
      </Animated>
    </div>
  );
}
