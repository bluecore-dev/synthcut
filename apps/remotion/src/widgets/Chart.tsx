import { interpolate, useCurrentFrame, useVideoConfig, Easing } from "remotion";
import type { ChartProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import { cardStyle, formatNumber, type WidgetProps } from "./common";

const PALETTE = ["#00C4FF", "#FFD60A", "#22C55E", "#FF6B6B", "#A78BFA", "#F97316", "#14B8A6", "#F472B6"];

export function Chart({ props, durationInFrames }: WidgetProps<ChartProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin, portrait } = useUnits();
  const accent = accentOf(props, theme);
  const grow = interpolate(frame, [fps * 0.25, fps * 1.4], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
  const W = portrait ? width * 0.8 : width * 0.5;
  const H = W * 0.6;
  const max = Math.max(...props.series.map((d) => Math.abs(d.value)), 1e-9);
  const n = props.series.length;
  const label = { fontFamily: FONT_STACK("Inter"), fontWeight: 700, fontSize: vmin * 2.2, fill: "rgba(255,255,255,0.85)" } as const;

  let body;
  if (props.kind === "pie") {
    const total = props.series.reduce((s, d) => s + Math.max(0, d.value), 0) || 1;
    const r = H * 0.42;
    let angle = -Math.PI / 2;
    body = props.series.map((d, i) => {
      const sweep = (Math.max(0, d.value) / total) * Math.PI * 2 * grow;
      const a0 = angle;
      const a1 = angle + sweep;
      angle = a1;
      const large = sweep > Math.PI ? 1 : 0;
      const cx = W / 2;
      const cy = H / 2;
      const path = `M ${cx} ${cy} L ${cx + r * Math.cos(a0)} ${cy + r * Math.sin(a0)} A ${r} ${r} 0 ${large} 1 ${cx + r * Math.cos(a1)} ${cy + r * Math.sin(a1)} Z`;
      return <path key={i} d={path} fill={PALETTE[i % PALETTE.length]} stroke="rgba(12,18,32,0.9)" strokeWidth={vmin * 0.3} />;
    });
  } else if (props.kind === "line") {
    const pts = props.series.map((d, i) => [((i + 0.5) / n) * W, H * 0.85 - (d.value / max) * H * 0.7] as const);
    const path = pts.map(([x, y], i) => `${i ? "L" : "M"} ${x} ${y}`).join(" ");
    const length = pts.reduce((s, [x, y], i) => (i ? s + Math.hypot(x - pts[i - 1]![0], y - pts[i - 1]![1]) : 0), 0);
    body = (
      <>
        <path d={path} fill="none" stroke={accent} strokeWidth={vmin * 0.8} strokeLinecap="round" strokeLinejoin="round" strokeDasharray={length} strokeDashoffset={length * (1 - grow)} />
        {pts.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={vmin * 1.1} fill="#fff" opacity={grow >= (i + 0.5) / n ? 1 : 0} />)}
        {props.series.map((d, i) => <text key={`l${i}`} x={pts[i]![0]} y={H * 0.97} textAnchor="middle" style={label}>{d.label}</text>)}
      </>
    );
  } else {
    const bw = (W / n) * 0.6;
    body = props.series.map((d, i) => {
      const h = (Math.abs(d.value) / max) * H * 0.7 * grow;
      const x = (i + 0.2) * (W / n);
      return (
        <g key={i}>
          <rect x={x} y={H * 0.85 - h} width={bw} height={h} rx={vmin * 0.8} fill={i === n - 1 ? accent : PALETTE[(i + 1) % PALETTE.length]} />
          <text x={x + bw / 2} y={H * 0.85 - h - vmin} textAnchor="middle" style={{ ...label, fill: "#fff" }}>{formatNumber(d.value * grow, d.value % 1 ? 1 : 0)}{props.unit}</text>
          <text x={x + bw / 2} y={H * 0.97} textAnchor="middle" style={label}>{d.label}</text>
        </g>
      );
    });
  }
  return (
    <div style={place("center", safe, width, height)}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={cardStyle(vmin, { padding: vmin * 2.6 })}>
          {props.title && <div style={{ fontWeight: 800, fontSize: vmin * 3.6, marginBottom: vmin * 1.2 }}>{props.title}</div>}
          <svg width={W} height={H}>{body}</svg>
          {props.kind === "pie" && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: vmin * 1.6, marginTop: vmin, fontFamily: FONT_STACK("Inter"), fontWeight: 700, fontSize: vmin * 2.2 }}>
              {props.series.map((d, i) => (
                <span key={i} style={{ display: "flex", alignItems: "center", gap: vmin * 0.6 }}>
                  <span style={{ width: vmin * 1.6, height: vmin * 1.6, borderRadius: vmin * 0.4, background: PALETTE[i % PALETTE.length] }} />
                  {d.label} {formatNumber(d.value, d.value % 1 ? 1 : 0)}{props.unit}
                </span>
              ))}
            </div>
          )}
        </div>
      </Animated>
    </div>
  );
}
