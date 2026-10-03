import { describe, expect, it } from "vitest";
import schema from "../src/generated/schema.json";
import { WIDGET_SAMPLES } from "../src/samples";
import { WIDGETS } from "../src/widgets";

describe("motion registry", () => {
  it("has one React widget per Python registry entry", () => {
    const python = Object.keys(schema.$defs.ComponentProps.properties).sort();
    expect(Object.keys(WIDGETS).sort()).toEqual(python);
    expect(Object.keys(WIDGET_SAMPLES).sort()).toEqual(python);
  });
});
