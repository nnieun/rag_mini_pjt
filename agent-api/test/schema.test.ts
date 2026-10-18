import { describe, expect, it } from "vitest";
import { AnalyzeInput, ClassificationResult, ExtractionResult } from "../src/schema.js";

describe("AnalyzeInput", () => {
  it("rejects empty text", () => {
    const result = AnalyzeInput.safeParse({ text: "", fields_to_extract: ["a"] });
    expect(result.success).toBe(false);
  });

  it("rejects an empty fields_to_extract list", () => {
    const result = AnalyzeInput.safeParse({ text: "hello", fields_to_extract: [] });
    expect(result.success).toBe(false);
  });

  it("accepts valid input", () => {
    const result = AnalyzeInput.safeParse({ text: "hello", fields_to_extract: ["amount"] });
    expect(result.success).toBe(true);
  });
});

describe("ClassificationResult", () => {
  it("rejects a category outside the enum", () => {
    const result = ClassificationResult.safeParse({
      category: "unknown_category",
      confidence: 0.5,
      reason: "x",
    });
    expect(result.success).toBe(false);
  });

  it("rejects confidence out of [0,1] range", () => {
    const result = ClassificationResult.safeParse({
      category: "invoice",
      confidence: 1.5,
      reason: "x",
    });
    expect(result.success).toBe(false);
  });
});

describe("ExtractionResult", () => {
  it("allows null values for unresolved fields", () => {
    const result = ExtractionResult.safeParse({
      fields: [{ name: "amount", value: null, source_quote: null }],
      missing_fields: ["amount"],
    });
    expect(result.success).toBe(true);
  });
});
