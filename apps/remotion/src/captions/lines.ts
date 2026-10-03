// Pure caption timing helpers (unit-tested): which line is on screen and
// where each word is relative to the playhead.
import type { CaptionLine, OverlayWord } from "../generated/types";

/** The line on screen at time ``t`` (lines are sorted and never overlap). */
export function activeLine(lines: CaptionLine[], t: number): CaptionLine | null {
  let lo = 0;
  let hi = lines.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const line = lines[mid]!;
    if (t < line.start) hi = mid - 1;
    else if (t >= line.end) lo = mid + 1;
    else return line;
  }
  return null;
}

export type WordState = "future" | "active" | "past";

export function wordState(word: OverlayWord, t: number): WordState {
  if (t < word.start) return "future";
  if (t < Math.max(word.end, word.start + 0.08)) return "active";
  return "past";
}

/** 0 before the word, 0..1 while it is spoken, 1 after. */
export function wordProgress(word: OverlayWord, t: number): number {
  const length = Math.max(word.end - word.start, 0.08);
  return Math.max(0, Math.min(1, (t - word.start) / length));
}
