import type { CSSProperties, ReactNode } from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig, Easing } from "remotion";

export type Enter = "fade" | "pop" | "slide_up" | "slide_left" | "none";
export type Exit = "fade" | "slide_down" | "shrink" | "none";

const CLAMP = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 0 → 1 over the entrance (spring), and 0 → 1 over the exit (ease in). */
export function useEnterExit(enter: Enter, exit: Exit, durationInFrames: number) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const inP = enter === "none" ? 1 : spring({ frame, fps, config: { damping: 15, stiffness: 170, mass: 0.7 }, durationInFrames: Math.round(0.5 * fps) });
  const exitLen = Math.min(Math.round(0.3 * fps), Math.floor(durationInFrames / 3));
  const outP = exit === "none" || exitLen < 1 ? 0 : interpolate(frame, [durationInFrames - exitLen, durationInFrames], [0, 1], { ...CLAMP, easing: Easing.in(Easing.cubic) });
  return { inP, outP };
}

export function animStyle(enter: Enter, exit: Exit, inP: number, outP: number, vmin: number): CSSProperties {
  let opacity = 1;
  let tx = 0;
  let ty = 0;
  let scale = 1;
  switch (enter) {
    case "fade": opacity *= inP; break;
    case "pop": opacity *= Math.min(1, inP * 1.6); scale *= 0.55 + 0.45 * inP; break;
    case "slide_up": opacity *= inP; ty += (1 - inP) * 9 * vmin; break;
    case "slide_left": opacity *= inP; tx += (1 - inP) * 14 * vmin; break;
    case "none": break;
  }
  switch (exit) {
    case "fade": opacity *= 1 - outP; break;
    case "slide_down": opacity *= 1 - outP; ty += outP * 9 * vmin; break;
    case "shrink": opacity *= 1 - outP; scale *= 1 - 0.45 * outP; break;
    case "none": break;
  }
  return { opacity, transform: `translate(${tx}px, ${ty}px) scale(${scale})` };
}

/** Wraps a widget's content in its entrance / exit animation. */
export function Animated({ enter, exit, durationInFrames, vmin, style, children }: {
  enter: Enter; exit: Exit; durationInFrames: number; vmin: number; style?: CSSProperties; children: ReactNode;
}) {
  const { inP, outP } = useEnterExit(enter, exit, durationInFrames);
  return <div style={{ ...style, ...animStyle(enter, exit, inP, outP, vmin) }}>{children}</div>;
}

/** Seconds since the item started (inside a <Sequence>). */
export function useSeconds() {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return frame / fps;
}

export { CLAMP };
