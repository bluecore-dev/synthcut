import { Img } from "remotion";
import type { PhoneMockupProps } from "../generated/types";
import { Animated } from "../lib/anim";
import { place, READABLE } from "../lib/layout";
import { accentOf, FONT_STACK, useTheme, useUnits } from "../lib/theme";
import type { WidgetProps } from "./common";

export function PhoneMockup({ props, durationInFrames }: WidgetProps<PhoneMockupProps>) {
  const { theme, safe, assets } = useTheme();
  const { width, height, vmin } = useUnits();
  const accent = accentOf(props, theme);
  const image = props.image_asset_id ? assets[props.image_asset_id] : undefined;
  const phoneH = height * (height > width ? 0.5 : 0.7);
  const phoneW = phoneH * 0.49;
  return (
    <div style={place(props.position, safe, width, height)}>
      <Animated enter={props.enter} exit={props.exit} durationInFrames={durationInFrames} vmin={vmin} style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{ width: phoneW, height: phoneH, borderRadius: phoneW * 0.14, background: "#0B0F19", padding: phoneW * 0.035, boxShadow: `0 ${vmin * 2}px ${vmin * 6}px rgba(0,0,0,.55)`, border: `${vmin * 0.25}px solid #2A3245`, position: "relative" }}>
          <div style={{ width: "100%", height: "100%", borderRadius: phoneW * 0.11, overflow: "hidden", background: image ? "#000" : `linear-gradient(160deg, ${accent}, #1A4F8A)` }}>
            {image && <Img src={image} style={{ width: "100%", height: "100%", objectFit: "cover" }} />}
          </div>
          <div style={{ position: "absolute", top: phoneW * 0.06, left: "50%", transform: "translateX(-50%)", width: phoneW * 0.3, height: phoneW * 0.07, borderRadius: phoneW, background: "#0B0F19" }} />
        </div>
        {props.caption && <div style={{ marginTop: vmin * 1.6, fontFamily: FONT_STACK("Montserrat"), fontWeight: 800, fontSize: vmin * 3, color: "#fff", textShadow: READABLE, maxWidth: phoneW * 1.6, textAlign: "center" }}>{props.caption}</div>}
      </Animated>
    </div>
  );
}
