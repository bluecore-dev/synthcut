import { spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { CTAProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import { Icon, type WidgetProps } from "./common";

const ICON = { subscribe: "bell", follow: "bell", like: "heart", comment: "comment", link: "link" } as const;

export function CTA({ props, durationInFrames }: WidgetProps<CTAProps>) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin } = useUnits();
  const accent = accentOf(props, theme);
  // A "tap" at 0.8 s: the button squeezes and the icon fills.
  const tapAt = Math.round(0.8 * fps);
  const tap = spring({ frame: frame - tapAt, fps, config: { damping: 9, stiffness: 260 }, durationInFrames: Math.round(0.4 * fps) });
  const squeeze = frame >= tapAt ? 1 - 0.08 * Math.sin(tap * Math.PI) : 1;
  const done = frame >= tapAt + Math.round(0.2 * fps);
  const pulse = 1 + 0.03 * Math.sin((frame / fps) * Math.PI * 2);
  return (
    <div style={place(props.position === "center" ? "center" : "bottom", safe, width, height)}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={{ display: "flex", alignItems: "center", gap: vmin * 1.6, padding: `${vmin * 1.6}px ${vmin * 3.2}px ${vmin * 1.6}px ${vmin * 1.8}px`,
          borderRadius: vmin * 10, background: done ? "#fff" : accent, color: done ? "#111" : "#fff", transform: `scale(${squeeze * pulse})`,
          boxShadow: `0 ${vmin}px ${vmin * 3.2}px rgba(0,0,0,0.4)`, fontFamily: FONT_STACK("Montserrat") }}>
          <div style={{ width: vmin * 6.4, height: vmin * 6.4, borderRadius: "50%", background: done ? accent : "rgba(255,255,255,0.22)", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Icon name={ICON[props.action]} size={vmin * 3.8} color="#fff" />
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: vmin * 3.8, lineHeight: 1.1 }}>{props.text}</div>
            {props.handle && <div style={{ fontWeight: 600, fontSize: vmin * 2.4, opacity: 0.8 }}>{props.handle}</div>}
          </div>
        </div>
      </Animated>
    </div>
  );
}
