import type { ReactNode } from "react";
import { AbsoluteFill, Easing, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { OverlayKey } from "../generated/types";

type Property = OverlayKey["property"];

const EASE: Record<OverlayKey["easing"], ((t: number) => number) | null> = {
  linear: (t) => t,
  ease_in: Easing.in(Easing.quad),
  ease_out: Easing.out(Easing.quad),
  ease_in_out: Easing.inOut(Easing.cubic),
  hold: null,
};

const DEFAULTS: Record<Property, number> = { x: 0, y: 0, scale: 1, rotation: 0, opacity: 1 };

/** The value of one property at ``frame``: held before the first key and
 *  after the last; each key's easing shapes the way to the next one. */
export function valueAt(keys: OverlayKey[], property: Property, frame: number): number {
  const ks = keys.filter((k) => k.property === property).sort((a, b) => a.frame - b.frame);
  if (ks.length === 0) return DEFAULTS[property];
  if (frame <= ks[0]!.frame) return ks[0]!.value;
  for (let i = 0; i < ks.length - 1; i++) {
    const a = ks[i]!;
    const b = ks[i + 1]!;
    if (frame < b.frame) {
      const ease = EASE[a.easing];
      if (ease === null) return a.value;
      return interpolate(frame, [a.frame, b.frame], [a.value, b.value], { easing: ease, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
    }
  }
  return ks[ks.length - 1]!.value;
}

/** After Effects-style transform of a whole component: x / y in frame
 *  widths / heights, scale, rotation in degrees, opacity. */
export function Keyframed({ keys, children }: { keys: OverlayKey[]; children: ReactNode }) {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  if (keys.length === 0) return <>{children}</>;
  const x = valueAt(keys, "x", frame) * width;
  const y = valueAt(keys, "y", frame) * height;
  const scale = valueAt(keys, "scale", frame);
  const rotation = valueAt(keys, "rotation", frame);
  const opacity = valueAt(keys, "opacity", frame);
  return (
    <AbsoluteFill style={{ transform: `translate(${x}px, ${y}px) scale(${scale}) rotate(${rotation}deg)`, opacity, transformOrigin: "50% 50%" }}>
      {children}
    </AbsoluteFill>
  );
}
