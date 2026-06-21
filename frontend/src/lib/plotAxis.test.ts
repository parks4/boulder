/**
 * Unit tests for plot axis helpers.
 *
 * Asserts:
 * - coerceNumericSeries converts string values to numbers.
 * - pressureYAxis pins the autorange baseline to zero and uses plain Pa ticks.
 */

import { describe, expect, it } from "vitest";
import { coerceNumericSeries, pressureYAxis } from "./plotAxis";

describe("plotAxis", () => {
  it("coerces string pressure samples to numeric series", () => {
    expect(coerceNumericSeries(["101325", "102000", "bad"])).toEqual([
      101325, 102000,
    ]);
  });

  it("pressureYAxis includes a zero baseline and fixed-format ticks", () => {
    expect(pressureYAxis("#ccc")).toEqual({
      title: { text: "Pressure (Pa)", font: { size: 12 } },
      gridcolor: "#ccc",
      rangemode: "tozero",
      tickformat: ",.0f",
      exponentformat: "none",
    });
  });
});
