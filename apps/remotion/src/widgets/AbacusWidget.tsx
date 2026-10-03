import { interpolate, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import type { AbacusWidgetProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import { cardStyle, formatNumber, type WidgetProps } from "./common";

/** A soroban: one upper bead (5) and four lower beads (1) per rod. */
export function AbacusWidget({ props, durationInFrames }: WidgetProps<AbacusWidgetProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin } = useUnits();
  const accent = accentOf(props, theme);
  const from = props.from_value ?? 0;
  const t = interpolate(frame, [fps * 0.3, Math.max(fps * 0.4, durationInFrames - fps * 0.6)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.inOut(Easing.cubic) });
  const value = Math.round(from + (props.value - from) * t);
  const digits = String(value).padStart(props.rods, "0").slice(-props.rods).split("").map(Number);
  const rodGap = vmin * 7.2;
  const bead = vmin * 5.6;
  const frameH = vmin * 38;
  const beam = vmin * 11;
  return (
    <div style={place(props.position, safe, width, height)}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={cardStyle(vmin, { padding: vmin * 2.6, display: "flex", flexDirection: "column", alignItems: "center" })}>
          <svg width={rodGap * props.rods + vmin * 2} height={frameH}>
            <rect x={0} y={beam} width="100%" height={vmin * 0.9} fill="#C08A4B" />
            {digits.map((d, i) => {
              const cx = vmin + rodGap * i + rodGap / 2;
              const upper = d >= 5;
              const lower = d % 5;
              return (
                <g key={i}>
                  <line x1={cx} x2={cx} y1={vmin} y2={frameH - vmin} stroke="rgba(255,255,255,0.35)" strokeWidth={vmin * 0.5} />
                  <rect x={cx - bead / 2} y={upper ? beam - bead * 0.55 - vmin * 0.1 : vmin * 1.2} width={bead} height={bead * 0.55} rx={bead * 0.27} fill={accent} />
                  {[0, 1, 2, 3].map((k) => {
                    const active = k < lower;
                    const y = active ? beam + vmin * 1.2 + k * bead * 0.6 : frameH - vmin * 1.2 - (4 - k) * bead * 0.6;
                    return <rect key={k} x={cx - bead / 2} y={y} width={bead} height={bead * 0.55} rx={bead * 0.27} fill={active ? accent : "rgba(255,255,255,0.75)"} />;
                  })}
                </g>
              );
            })}
          </svg>
          <div style={{ marginTop: vmin, fontFamily: FONT_STACK("Montserrat"), fontWeight: 900, fontSize: vmin * 6, color: "#fff" }}>{formatNumber(value, 0)}</div>
        </div>
      </Animated>
    </div>
  );
}
