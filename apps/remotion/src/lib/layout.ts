import type { CSSProperties } from "react";
import type { SafeZone } from "../generated/types";

export type Corner = "top" | "bottom" | "center" | "top_left" | "top_right" | "bottom_left" | "bottom_right" | "left" | "right";

/** Absolute placement inside the safe zone (platform UI never covers it). */
export function place(corner: Corner, safe: SafeZone, width: number, height: number): CSSProperties {
  const top = safe.top * height;
  const bottom = safe.bottom * height;
  const left = safe.left * width;
  const right = safe.right * width;
  const base: CSSProperties = { position: "absolute", display: "flex" };
  switch (corner) {
    case "top": return { ...base, top, left, right, justifyContent: "center" };
    case "bottom": return { ...base, bottom, left, right, justifyContent: "center" };
    case "center": return { ...base, top, bottom, left, right, alignItems: "center", justifyContent: "center" };
    case "top_left": return { ...base, top, left };
    case "top_right": return { ...base, top, right };
    case "bottom_left": return { ...base, bottom, left };
    case "bottom_right": return { ...base, bottom, right };
    case "left": return { ...base, top, bottom, left, alignItems: "center" };
    case "right": return { ...base, top, bottom, right, alignItems: "center" };
  }
}

/** Text shadow that keeps white text readable over any footage. */
export const READABLE = "0 0.12em 0.35em rgba(0,0,0,0.55), 0 0 0.08em rgba(0,0,0,0.7)";
