import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { CalloutProps } from "../generated/types";
import { useEnterExit } from "../lib/anim";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

/** A label with an arrow drawn to a point of interest. */
export function Callout({ props, durationInFrames }: WidgetProps<CalloutProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme } = useTheme();
  const { width, height, vmin } = useUnits();
  const { outP } = useEnterExit("none", props.exit, durationInFrames);
  const color = accentOf(props, theme);
  const tx = props.target.x * width;
  const ty = props.target.y * height;
  const off = vmin * 16;
  const [lx, ly] = props.side === "left" ? [tx - off, ty - off * 0.4] : props.side === "right" ? [tx + off, ty - off * 0.4] : props.side === "top" ? [tx, ty - off] : [tx, ty + off];
  const draw = props.enter === "none" ? 1 : interpolate(frame, [0, fps * 0.4], [0, 1], { extrapolateRight: "clamp" });
  const label = interpolate(frame, [fps * 0.3, fps * 0.55], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const len = Math.hypot(tx - lx, ty - ly);
  const ang = Math.atan2(ty - ly, tx - lx);
  const head = vmin * 2.2;
  return (
    <div style={{ position: "absolute", inset: 0, opacity: 1 - outP }}>
      <svg width={width} height={height} style={{ position: "absolute", inset: 0 }}>
        <line x1={lx} y1={ly} x2={lx + (tx - lx) * draw} y2={ly + (ty - ly) * draw} stroke={color} strokeWidth={vmin * 0.7} strokeLinecap="round" />
        {draw >= 1 && (
          <path d={`M ${tx} ${ty} L ${tx - head * Math.cos(ang - 0.45)} ${ty - head * Math.sin(ang - 0.45)} M ${tx} ${ty} L ${tx - head * Math.cos(ang + 0.45)} ${ty - head * Math.sin(ang + 0.45)}`}
            stroke={color} strokeWidth={vmin * 0.7} strokeLinecap="round" fill="none" />
        )}
        <circle cx={tx} cy={ty} r={vmin * 1.2 * draw} fill="none" stroke={color} strokeWidth={vmin * 0.4} opacity={len > 0 ? 1 : 0} />
      </svg>
      <div style={{ position: "absolute", left: lx, top: ly, transform: `translate(${props.side === "left" ? "-100%" : props.side === "right" ? "0" : "-50%"}, ${props.side === "bottom" ? "0" : "-100%"}) scale(${0.8 + 0.2 * label})`,
        opacity: label, padding: `${vmin}px ${vmin * 1.8}px`, borderRadius: vmin * 1.2, background: color, color: "#fff", whiteSpace: "nowrap",
        fontFamily: FONT_STACK("Montserrat"), fontWeight: 800, fontSize: vmin * 3, boxShadow: `0 ${vmin * 0.6}px ${vmin * 2}px rgba(0,0,0,.35)` }}>
        {props.text}
      </div>
    </div>
  );
}
