import type { NotificationProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { FONT_STACK, useTheme, useUnits } from "../lib/theme";
import { Icon, type WidgetProps } from "./common";

const APP_COLOR = { telegram: "#27A7E7", instagram: "#E1306C", message: "#34C759", bell: "#FF9500" } as const;

export function Notification({ props, durationInFrames }: WidgetProps<NotificationProps>) {
  const { safe } = useTheme();
  const { width, height, vmin, portrait } = useUnits();
  const w = portrait ? width * 0.86 : width * 0.36;
  return (
    <div style={{ position: "absolute", top: safe.top * height, right: portrait ? (width - w) / 2 : safe.right * width }}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin}>
        <div style={{ width: w, display: "flex", gap: vmin * 1.6, padding: vmin * 1.8, borderRadius: vmin * 2.6, background: "rgba(245,245,247,0.94)", color: "#111",
          boxShadow: `0 ${vmin}px ${vmin * 4}px rgba(0,0,0,.35)`, fontFamily: FONT_STACK("Inter") }}>
          <div style={{ width: vmin * 6, height: vmin * 6, borderRadius: vmin * 1.5, background: APP_COLOR[props.icon], display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Icon name={props.icon} size={vmin * 3.8} color="#fff" />
          </div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: vmin * 1.9, color: "#6B7280", fontWeight: 500 }}>
              <span style={{ textTransform: "uppercase", letterSpacing: "0.04em" }}>{props.app}</span>
              <span>hozir</span>
            </div>
            <div style={{ fontWeight: 700, fontSize: vmin * 2.7, marginTop: vmin * 0.3 }}>{props.title}</div>
            {props.body && <div style={{ fontSize: vmin * 2.4, color: "#374151", marginTop: vmin * 0.2, lineHeight: 1.25 }}>{props.body}</div>}
          </div>
        </div>
      </Animated>
    </div>
  );
}
