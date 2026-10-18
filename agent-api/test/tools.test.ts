import { describe, expect, it } from "vitest";
import { executeLookupGlossary } from "../src/tools.js";

describe("executeLookupGlossary", () => {
  it("resolves a known abbreviation case-insensitively", () => {
    expect(executeLookupGlossary({ term: "NDA" })).toContain("비밀유지계약");
  });

  it("returns a not-found message for unknown terms", () => {
    expect(executeLookupGlossary({ term: "zzz" })).toContain("찾을 수 없습니다");
  });
});
