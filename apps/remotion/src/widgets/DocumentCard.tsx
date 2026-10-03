import { Img, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { DocumentCardProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

export function DocumentCard({ props, durationInFrames }: WidgetProps<DocumentCardProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe, assets } = useTheme();
  const { width, height, vmin, portrait } = useUnits();
  const accent = accentOf(props, theme);
  const image = props.image_asset_id ? assets[props.image_asset_id] : undefined;
  const tilt = interpolate(frame, [0, fps * 0.6], [-4, -1.5], { extrapolateRight: "clamp" });
  return (
    <div style={place("center", safe, width, height)}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={{ width: portrait ? width * 0.74 : width * 0.42, background: "#fff", borderRadius: vmin * 1.6, overflow: "hidden", transform: `rotate(${tilt}deg)`,
          boxShadow: `0 ${vmin * 2}px ${vmin * 6}px rgba(0,0,0,.5)`, fontFamily: FONT_STACK("Inter"), color: "#111827" }}>
          <div style={{ height: vmin * 1.2, background: accent }} />
          {image && <Img src={image} style={{ width: "100%", display: "block", maxHeight: vmin * 40, objectFit: "cover" }} />}
          <div style={{ padding: vmin * 3 }}>
            <div style={{ fontFamily: FONT_STACK("Montserrat"), fontWeight: 800, fontSize: vmin * 4, lineHeight: 1.2 }}>{props.title}</div>
            {props.subtitle && <div style={{ marginTop: vmin, fontSize: vmin * 2.6, color: "#4B5563" }}>{props.subtitle}</div>}
            {props.lines.map((line, i) => {
              const show = interpolate(frame, [fps * (0.35 + i * 0.15), fps * (0.55 + i * 0.15)], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
              return (
                <div key={i} style={{ marginTop: vmin * 1.2, fontSize: vmin * 2.5, color: "#374151", opacity: show, display: "flex", gap: vmin }}>
                  <span style={{ color: accent, fontWeight: 700 }}>•</span>
                  {line}
                </div>
              );
            })}
          </div>
        </div>
      </Animated>
    </div>
  );
}
