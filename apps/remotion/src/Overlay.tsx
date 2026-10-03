import { AbsoluteFill, Sequence } from "remotion";
import { Captions } from "./captions/Captions";
import type { OverlayProps } from "./generated/types";
import { loadFonts } from "./lib/fonts";
import { ThemeProvider } from "./lib/theme";
import { WIDGETS, type ComponentName } from "./widgets";

loadFonts();

/** The whole motion layer of a plan on a transparent background (spec §20,
 *  rule 19): graphics by layer, captions on top. FFmpeg composites it. */
export function Overlay(props: OverlayProps) {
  const items = [...props.items].sort((a, b) => a.layer - b.layer || a.from_frame - b.from_frame);
  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      <ThemeProvider value={{ theme: props.theme, safe: props.safe_zone, assets: props.assets }}>
        {items.map((item) => {
          const Widget = WIDGETS[item.component as ComponentName];
          if (!Widget) throw new Error(`${item.component} is not in the motion registry`); // validated upstream
          return (
            <Sequence key={item.id} from={item.from_frame} durationInFrames={item.duration_frames} name={`${item.component} ${item.id}`}>
              <Widget props={item.props as never} durationInFrames={item.duration_frames} />
            </Sequence>
          );
        })}
        {props.captions && <Captions captions={props.captions} />}
      </ThemeProvider>
    </AbsoluteFill>
  );
}
