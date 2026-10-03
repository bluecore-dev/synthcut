import { Composition, type CalculateMetadataFunction } from "remotion";
import type { OverlayProps } from "./generated/types";
import { Overlay } from "./Overlay";
import { sampleOverlay, widgetOverlay } from "./samples";
import { WIDGETS, type ComponentName } from "./widgets";

type Input = OverlayProps & Record<string, unknown>;

// Size, rate and length come from the props: one composition serves every preset.
const metadata: CalculateMetadataFunction<Input> = ({ props }) => ({
  width: props.width,
  height: props.height,
  fps: props.fps,
  durationInFrames: props.duration_in_frames,
});

const Component = Overlay as unknown as React.FC<Input>;

export function Root() {
  return (
    <>
      <Composition id="Overlay" component={Component} defaultProps={sampleOverlay() as Input} calculateMetadata={metadata} width={1080} height={1920} fps={30} durationInFrames={150} />
      {(Object.keys(WIDGETS) as ComponentName[]).map((name) => (
        <Composition key={name} id={`Widget-${name}`} component={Component} defaultProps={widgetOverlay(name) as Input} calculateMetadata={metadata} width={1080} height={1920} fps={30} durationInFrames={150} />
      ))}
    </>
  );
}
