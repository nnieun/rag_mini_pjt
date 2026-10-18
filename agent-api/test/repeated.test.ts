import { describe, expect, it } from "vitest";
import { compareBinaryRates, repeatedRun, summarizeBinary } from "../src/repeated.js";

describe("repeatedRun", () => {
  it("calls fn the requested number of times and collects results in order", async () => {
    const results = await repeatedRun(async (i) => i * 2, 4);
    expect(results).toEqual([0, 2, 4, 6]);
  });
});

describe("summarizeBinary", () => {
  it("computes pass rate and a Wilson interval that contains the observed rate", () => {
    const summary = summarizeBinary([true, true, true, false]);
    expect(summary.n).toBe(4);
    expect(summary.passCount).toBe(3);
    expect(summary.passRate).toBe(0.75);
    expect(summary.wilsonCi95[0]).toBeLessThanOrEqual(0.75);
    expect(summary.wilsonCi95[1]).toBeGreaterThanOrEqual(0.75);
  });

  it("returns a zero-width interval for an empty sample", () => {
    const summary = summarizeBinary([]);
    expect(summary.passRate).toBe(0);
    expect(summary.wilsonCi95).toEqual([0, 0]);
  });
});

describe("compareBinaryRates", () => {
  it("flags a large, consistent improvement as statistically significant", () => {
    const before = Array(30).fill(false);
    const after = Array(30).fill(true);
    const comparison = compareBinaryRates(before, after);
    expect(comparison.diff).toBeCloseTo(1, 5);
    expect(comparison.significantAt05).toBe(true);
  });

  it("does not flag a tiny difference on a small sample as significant", () => {
    const before = [true, false, true, false, true];
    const after = [true, false, true, false, false];
    const comparison = compareBinaryRates(before, after);
    expect(comparison.significantAt05).toBe(false);
  });
});
