import { describe, expect, it } from "vitest";
import { activeLine, wordProgress, wordState } from "../src/captions/lines";
import type { CaptionLine } from "../src/generated/types";

const lines: CaptionLine[] = [
  { start: 0.2, end: 1.4, words: [{ text: "Assalomu", start: 0.2, end: 0.7 }, { text: "alaykum", start: 0.75, end: 1.3 }] },
  { start: 1.5, end: 2.9, words: [{ text: "bugun", start: 1.5, end: 1.8 }] },
  { start: 4.0, end: 5.0, words: [{ text: "oxiri", start: 4.0, end: 4.6 }] },
];

describe("caption timing", () => {
  it("finds the line on screen, and nothing in gaps", () => {
    expect(activeLine(lines, 0.1)).toBeNull();
    expect(activeLine(lines, 0.2)?.words[0]?.text).toBe("Assalomu");
    expect(activeLine(lines, 1.45)).toBeNull(); // gap between lines
    expect(activeLine(lines, 2.0)?.words[0]?.text).toBe("bugun");
    expect(activeLine(lines, 4.99)?.words[0]?.text).toBe("oxiri");
    expect(activeLine(lines, 5.0)).toBeNull(); // end is exclusive
  });

  it("tracks each word against the playhead", () => {
    const w = lines[0]!.words[1]!;
    expect(wordState(w, 0.5)).toBe("future");
    expect(wordState(w, 1.0)).toBe("active");
    expect(wordState(w, 1.31)).toBe("past");
    expect(wordProgress(w, 0.75)).toBe(0);
    expect(wordProgress(w, 1.025)).toBeCloseTo(0.5);
    expect(wordProgress(w, 2)).toBe(1);
  });

  it("keeps a zero-length word visible for a moment", () => {
    const blip = { text: "a", start: 1, end: 1 };
    expect(wordState(blip, 1.05)).toBe("active");
  });
});
