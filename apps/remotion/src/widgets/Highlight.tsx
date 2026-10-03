import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { HighlightProps } from "../generated/types";
import { useEnterExit } from "../lib/anim";
import { accentOf, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

/** A marker stroke drawn around / under a region of the picture. */
export function Highlight({ props, durationInFrames }: WidgetProps<HighlightProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme } = useTheme();
  const { width, height, vmin } = useUnits();
  const { outP } = useEnterExit("none", props.exit, durationInFrames);
  const color = accentOf(props, theme);
  const draw = props.enter === "none" ? 1 : interpolate(frame, [0, fps * 0.45], [0, 1], { extrapolateRight: "clamp" });
  const x = props.region.x * width;
  const y = props.region.y * height;
  const w = props.region.width * width;
  const h = props.region.height * height;
  const sw = vmin * 0.9;
  let shape;
  let length;
  if (props.shape === "circle") {
    const rx = w / 2 + sw;
    const ry = h / 2 + sw;
    length = Math.PI * (3 * (rx + ry) - Math.sqrt((3 * rx + ry) * (rx + 3 * ry)));
    shape = <ellipse cx={x + w / 2} cy={y + h / 2} rx={rx} ry={ry} />;
  } else if (props.shape === "underline") {
    length = w;
    shape = <path d={`M ${x} ${y + h} Q ${x + w / 2} ${y + h + vmin * 1.2} ${x + w} ${y + h - vmin * 0.4}`} />;
  } else {
    length = 2 * (w + h);
    shape = <rect x={x} y={y} width={w} height={h} rx={vmin} />;
  }
  return (
    <svg width={width} height={height} style={{ position: "absolute", inset: 0, opacity: 1 - outP }}>
      {props.shape === "box" && <rect x={x} y={y} width={w} height={h} rx={vmin} fill={color} opacity={0.18 * draw} />}
      <g fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeDasharray={length} strokeDashoffset={length * (1 - draw)}>
        {shape}
      </g>
    </svg>
  );
}
