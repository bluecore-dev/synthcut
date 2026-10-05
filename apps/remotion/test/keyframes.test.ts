import { describe, expect, it } from "vitest";
import type { OverlayKey } from "../src/generated/types";
import { valueAt } from "../src/lib/keyframes";

const k = (frame: number, property: OverlayKey["property"], value: number, easing: OverlayKey["easing"] = "linear"): OverlayKey => ({ frame, property, value, easing });

describe("graphics keyframes", () => {
  it("holds outside the keys and interpolates between them", () => {
    const keys = [k(10, "x", 0), k(20, "x", 0.5)];
    expect(valueAt(keys, "x", 0)).toBe(0);
    expect(valueAt(keys, "x", 15)).toBeCloseTo(0.25);
    expect(valueAt(keys, "x", 99)).toBe(0.5);
    expect(valueAt(keys, "scale", 15)).toBe(1); // untouched properties keep their defaults
    expect(valueAt(keys, "opacity", 15)).toBe(1);
  });

  it("eases and holds", () => {
    const eased = [k(0, "scale", 1, "ease_in_out"), k(30, "scale", 2)];
    expect(valueAt(eased, "scale", 3)).toBeLessThan(1.1); // slow start
    expect(valueAt(eased, "scale", 15)).toBeCloseTo(1.5, 1);
    const held = [k(0, "rotation", 0, "hold"), k(30, "rotation", 90)];
    expect(valueAt(held, "rotation", 29)).toBe(0);
    expect(valueAt(held, "rotation", 30)).toBe(90);
  });
});
