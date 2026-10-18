import OpenAI from "openai";
import { describe, expect, it, vi } from "vitest";
import { OpenAiProvider } from "../src/providers/openai.js";
import { TransientError } from "../src/retry.js";

describe("OpenAiProvider", () => {
  it("maps a tool_calls response into generic ToolCalls", async () => {
    const create = vi.fn().mockResolvedValue({
      choices: [
        {
          message: {
            content: null,
            tool_calls: [
              {
                id: "call_1",
                type: "function",
                function: { name: "report_analysis", arguments: '{"a":1}' },
              },
            ],
          },
        },
      ],
    });
    const provider = new OpenAiProvider(
      { chat: { completions: { create } } } as never,
      "gpt-4o-mini",
    );

    const result = await provider.chatWithTools({
      messages: [
        { role: "user", text: "hi" },
        {
          role: "assistant",
          toolCalls: [{ id: "call_0", name: "lookup_glossary", input: { term: "nda" } }],
        },
        { role: "user", toolResults: [{ toolCallId: "call_0", content: "비밀유지계약" }] },
      ],
      tools: [{ name: "report_analysis", description: "d", inputSchema: {} }],
    });

    expect(result.toolCalls).toEqual([{ id: "call_1", name: "report_analysis", input: { a: 1 } }]);
    const sentMessages = create.mock.calls[0][0].messages;
    expect(sentMessages).toEqual([
      { role: "user", content: "hi" },
      {
        role: "assistant",
        content: null,
        tool_calls: [
          { id: "call_0", type: "function", function: { name: "lookup_glossary", arguments: '{"term":"nda"}' } },
        ],
      },
      { role: "tool", tool_call_id: "call_0", content: "비밀유지계약" },
    ]);
  });

  it("converts a 429 API error into a TransientError", async () => {
    const apiError = Object.create(OpenAI.APIError.prototype);
    Object.assign(apiError, { status: 429, message: "rate limited" });
    const create = vi.fn().mockRejectedValue(apiError);
    const provider = new OpenAiProvider(
      { chat: { completions: { create } } } as never,
      "gpt-4o-mini",
    );

    await expect(
      provider.chatWithTools({ messages: [{ role: "user", text: "hi" }], tools: [] }),
    ).rejects.toBeInstanceOf(TransientError);
  });
});
