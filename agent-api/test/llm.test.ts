import { describe, expect, it, vi } from "vitest";
import { analyzeDocument } from "../src/llm.js";
import type { ChatWithToolsResult, LlmProvider } from "../src/providers/types.js";

function fakeProvider(chatWithTools: (params: unknown) => Promise<ChatWithToolsResult>): LlmProvider {
  return { name: "anthropic", chatWithTools: chatWithTools as LlmProvider["chatWithTools"] };
}

describe("analyzeDocument", () => {
  it("returns a validated result when the model reports analysis directly", async () => {
    const chatWithTools = vi.fn().mockResolvedValue({
      toolCalls: [
        {
          id: "call_1",
          name: "report_analysis",
          input: {
            category: "invoice",
            confidence: 0.9,
            reason: "금액과 발행일이 명시됨",
            fields: [{ name: "amount", value: "100000", source_quote: "100,000원" }],
            missing_fields: [],
          },
        },
      ],
    });
    const provider = fakeProvider(chatWithTools);

    const result = await analyzeDocument(
      { text: "청구서: 100,000원", fields_to_extract: ["amount"] },
      provider,
    );

    expect(result.status).toBe("ok");
    expect(result.classification.category).toBe("invoice");
    expect(result.extraction.fields[0]?.value).toBe("100000");
    expect(chatWithTools).toHaveBeenCalledTimes(1);
  });

  it("executes a glossary tool call before reporting analysis", async () => {
    const chatWithTools = vi
      .fn()
      .mockResolvedValueOnce({
        toolCalls: [{ id: "call_1", name: "lookup_glossary", input: { term: "NDA" } }],
      })
      .mockResolvedValueOnce({
        toolCalls: [
          {
            id: "call_2",
            name: "report_analysis",
            input: {
              category: "contract",
              confidence: 0.8,
              reason: "NDA 조항 포함",
              fields: [],
              missing_fields: ["effective_date"],
            },
          },
        ],
      });
    const provider = fakeProvider(chatWithTools);

    const result = await analyzeDocument(
      { text: "본 NDA는...", fields_to_extract: ["effective_date"] },
      provider,
    );

    expect(chatWithTools).toHaveBeenCalledTimes(2);
    expect(result.status).toBe("needs_review");
    expect(result.extraction.missing_fields).toEqual(["effective_date"]);
  });

  it("marks the result as failed when the model's output fails schema validation", async () => {
    const chatWithTools = vi.fn().mockResolvedValue({
      toolCalls: [
        {
          id: "call_1",
          name: "report_analysis",
          input: {
            category: "not_a_real_category",
            confidence: 2,
            reason: "",
            fields: [],
            missing_fields: [],
          },
        },
      ],
    });
    const provider = fakeProvider(chatWithTools);

    const result = await analyzeDocument({ text: "x", fields_to_extract: ["a"] }, provider);

    expect(result.status).toBe("failed");
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it("marks the result as failed when the model never calls report_analysis", async () => {
    const chatWithTools = vi.fn().mockResolvedValue({ toolCalls: [], text: "모르겠습니다" });
    const provider = fakeProvider(chatWithTools);

    const result = await analyzeDocument({ text: "x", fields_to_extract: ["a"] }, provider);

    expect(result.status).toBe("failed");
  });
});
