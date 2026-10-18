import { describe, expect, it, vi } from "vitest";
import { judgeAnswer } from "../src/judge.js";
import type { ChatWithToolsResult, LlmProvider } from "../src/providers/types.js";
import { AnalyzeResult } from "../src/schema.js";

function fakeProvider(chatWithTools: (params: unknown) => Promise<ChatWithToolsResult>): LlmProvider {
  return { name: "anthropic", chatWithTools: chatWithTools as LlmProvider["chatWithTools"] };
}

const input = { text: "본 NDA는...", fields_to_extract: ["effective_date"] };
const output: AnalyzeResult = {
  classification: { category: "contract", confidence: 0.9, reason: "NDA 조항 포함" },
  extraction: { fields: [], missing_fields: ["effective_date"] },
  status: "needs_review",
  errors: [],
};

describe("judgeAnswer", () => {
  it("parses a valid judgment into a JudgeVerdict", async () => {
    const chatWithTools = vi.fn().mockResolvedValue({
      toolCalls: [
        {
          id: "call_1",
          name: "submit_judgment",
          input: {
            criteria: [
              { criterion_id: "category_correct", score: 1, rationale: "계약서로 올바르게 분류됨" },
              { criterion_id: "groundedness", score: 1, rationale: "환각 없음" },
            ],
            overall_pass: true,
            summary: "전반적으로 양호함",
          },
        },
      ],
    });
    const provider = fakeProvider(chatWithTools);

    const verdict = await judgeAnswer(provider, input, output);

    expect(verdict.overall_pass).toBe(true);
    expect(verdict.criteria).toHaveLength(2);
    expect(chatWithTools).toHaveBeenCalledTimes(1);
  });

  it("drops criteria with unknown ids before validation", async () => {
    const chatWithTools = vi.fn().mockResolvedValue({
      toolCalls: [
        {
          id: "call_1",
          name: "submit_judgment",
          input: {
            criteria: [
              { criterion_id: "category_correct", score: 1, rationale: "ok" },
              { criterion_id: "made_up_criterion", score: 1, rationale: "ok" },
            ],
            overall_pass: true,
            summary: "ok",
          },
        },
      ],
    });
    const provider = fakeProvider(chatWithTools);

    const verdict = await judgeAnswer(provider, input, output);

    expect(verdict.criteria.map((c) => c.criterion_id)).toEqual(["category_correct"]);
  });

  it("throws when the judge does not call submit_judgment", async () => {
    const chatWithTools = vi.fn().mockResolvedValue({ toolCalls: [], text: "모르겠음" });
    const provider = fakeProvider(chatWithTools);

    await expect(judgeAnswer(provider, input, output)).rejects.toThrow("submit_judgment");
  });
});
