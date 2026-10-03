import type { CSSProperties } from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { CaptionsOverlay, OverlayWord } from "../generated/types";
import { READABLE } from "../lib/layout";
import { FONT_STACK, useTheme, useUnits } from "../lib/theme";
import { activeLine, wordProgress, wordState } from "./lines";

/** Subtitle layer (spec §20 "Subtitle engine"): one short line at a time,
 *  word timing from transcript/1, placed inside the platform safe zone. */
export function Captions({ captions }: { captions: CaptionsOverlay }) {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const { theme, safe } = useTheme();
  const { width, height, vmin, portrait } = useUnits();
  const t = frame / fps;
  const line = activeLine(captions.lines, t);
  if (!line) return null;

  const bold = captions.style === "bold";
  const fontSize = vmin * (portrait ? (bold ? 8.4 : 7.2) : bold ? 7.0 : 6.0);
  const box: CSSProperties = {
    position: "absolute",
    left: safe.left * width,
    right: safe.right * width,
    display: "flex",
    justifyContent: "center",
    ...(captions.position === "bottom"
      ? { bottom: safe.bottom * height + vmin * 2 }
      : captions.position === "top"
        ? { top: safe.top * height + vmin * 2 }
        : { top: 0, bottom: 0, alignItems: "center" }),
  };
  // The line pops in at its start; a minimal line fades.
  const lineFrame = frame - Math.round(line.start * fps);
  const pop = spring({ frame: lineFrame, fps, config: { damping: 14, stiffness: 200, mass: 0.6 }, durationInFrames: Math.round(0.3 * fps) });
  const text: CSSProperties = {
    fontFamily: FONT_STACK(captions.style === "minimal" ? "Inter" : "Montserrat"),
    fontWeight: bold ? 900 : captions.style === "minimal" ? 700 : 800,
    fontSize,
    lineHeight: 1.18,
    color: theme.text,
    textAlign: "center",
    textTransform: bold ? "uppercase" : "none",
    letterSpacing: bold ? "0.01em" : "0",
    maxWidth: "100%",
  };

  if (captions.style === "minimal") {
    const fade = interpolate(lineFrame, [0, Math.round(0.15 * fps)], [0, 1], { extrapolateRight: "clamp" });
    return (
      <div style={box}>
        <div style={{ ...text, opacity: fade, background: "rgba(0,0,0,0.55)", borderRadius: vmin * 1.2, padding: `${vmin * 0.6}px ${vmin * 1.6}px` }}>
          {line.words.map((w) => w.text).join(" ")}
        </div>
      </div>
    );
  }

  return (
    <div style={box}>
      <div style={{ ...text, transform: `scale(${0.85 + 0.15 * pop})`, textShadow: READABLE }}>
        {line.words.map((w, i) => (
          <Word key={i} word={w} t={t} style={captions.style} highlight={theme.highlight} vmin={vmin} fps={fps} />
        ))}
      </div>
    </div>
  );
}

function Word({ word, t, style, highlight, vmin, fps }: {
  word: OverlayWord; t: number; style: CaptionsOverlay["style"]; highlight: string; vmin: number; fps: number;
}) {
  const state = wordState(word, t);
  const gap = <span> </span>;
  if (style === "karaoke") {
    const p = wordProgress(word, t) * 100;
    return (
      <>
        <span style={{ backgroundImage: `linear-gradient(90deg, ${highlight} ${p}%, rgba(255,255,255,0.92) ${p}%)`, WebkitBackgroundClip: "text", backgroundClip: "text", color: "transparent", textShadow: "none", filter: "drop-shadow(0 0.08em 0.2em rgba(0,0,0,0.6))" }}>
          {word.text}
        </span>
        {gap}
      </>
    );
  }
  if (style === "bold") {
    const active = state === "active";
    return (
      <>
        <span style={{ display: "inline-block", padding: "0 0.12em", borderRadius: vmin * 0.8, background: active ? highlight : "transparent", color: active ? "#111" : undefined, WebkitTextStroke: active ? "0" : `${vmin * 0.35}px #000`, paintOrder: "stroke fill", textShadow: active ? "none" : undefined }}>
          {word.text}
        </span>
        {gap}
      </>
    );
  }
  // dynamic: words appear as they are spoken, the current one pops and glows
  const since = Math.max(0, t - word.start) * fps;
  const pop = state === "future" ? 0 : spring({ frame: since, fps, config: { damping: 12, stiffness: 220, mass: 0.5 }, durationInFrames: Math.round(0.25 * fps) });
  const active = state === "active";
  return (
    <>
      <span style={{ display: "inline-block", opacity: state === "future" ? 0 : 1, transform: `scale(${(active ? 1.12 : 1) * (0.7 + 0.3 * pop)})`, color: active ? highlight : undefined }}>
        {word.text}
      </span>
      {gap}
    </>
  );
}
