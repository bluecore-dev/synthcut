import { interpolate, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import type { ScoreCounterProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place, READABLE } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import { formatNumber, type WidgetProps } from "./common";

export function ScoreCounter({ props, durationInFrames }: WidgetProps<ScoreCounterProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin } = useUnits();
  const accent = accentOf(props, theme);
  const t = interpolate(frame, [fps * 0.2, Math.min(durationInFrames - fps * 0.3, fps * 2.2)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  const value = props.from_value + (props.to_value - props.from_value) * t;
  return (
    <div style={place(props.position, safe, width, height)}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", fontFamily: FONT_STACK("Montserrat"), textShadow: READABLE }}>
          <div style={{ fontWeight: 900, fontSize: vmin * 13, color: "#fff", lineHeight: 1 }}>
            <span style={{ color: accent }}>{props.prefix}</span>
            {formatNumber(value, props.decimals)}
            <span style={{ color: accent }}>{props.suffix}</span>
          </div>
          {props.label && <div style={{ marginTop: vmin * 1.2, fontWeight: 800, fontSize: vmin * 3.4, color: "#fff", textTransform: "uppercase", letterSpacing: "0.06em" }}>{props.label}</div>}
        </div>
      </Animated>
    </div>
  );
}
