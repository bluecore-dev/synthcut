import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { GamifiedTimerProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

export function GamifiedTimer({ props, durationInFrames }: WidgetProps<GamifiedTimerProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin } = useUnits();
  const elapsed = frame / fps;
  const left = Math.max(0, props.total_seconds - elapsed);
  const shown = Math.ceil(left - 1e-6);
  const warn = left <= props.warn_at && left > 0;
  const color = warn ? "#FF3B30" : accentOf(props, theme);
  const size = vmin * 22;
  const r = size * 0.42;
  const circ = 2 * Math.PI * r;
  const progress = Math.min(1, elapsed / props.total_seconds);
  const pulse = warn ? 1 + 0.06 * Math.sin((frame / fps) * Math.PI * 4) : 1;
  const mm = Math.floor(shown / 60);
  const ss = String(shown % 60).padStart(2, "0");
  return (
    <div style={place(props.position, safe, width, height)}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", transform: `scale(${pulse})` }}>
          <svg width={size} height={size}>
            <circle cx={size / 2} cy={size / 2} r={r} fill="rgba(12,18,32,0.82)" stroke="rgba(255,255,255,0.15)" strokeWidth={vmin * 1.6} />
            <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={vmin * 1.6} strokeLinecap="round"
              strokeDasharray={circ} strokeDashoffset={circ * progress} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
            <text x="50%" y="53%" textAnchor="middle" dominantBaseline="middle" fill="#fff"
              style={{ fontFamily: FONT_STACK("Montserrat"), fontWeight: 900, fontSize: props.total_seconds >= 60 ? vmin * 5.2 : vmin * 7.5 }}>
              {props.total_seconds >= 60 ? `${mm}:${ss}` : shown}
            </text>
          </svg>
          {props.label && (
            <div style={{ marginTop: vmin, color: "#fff", fontFamily: FONT_STACK("Montserrat"), fontWeight: 800, fontSize: vmin * 3, textShadow: "0 2px 8px rgba(0,0,0,.6)", opacity: interpolate(frame, [0, fps * 0.3], [0, 1], { extrapolateRight: "clamp" }) }}>
              {props.label}
            </div>
          )}
        </div>
      </Animated>
    </div>
  );
}
