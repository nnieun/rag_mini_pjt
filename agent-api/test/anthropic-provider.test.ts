import Anthropic from "@anthropic-ai/sdk";
import { describe, expect, it, vi } from "vitest";
import { AnthropicProvider } from "../src/providers/anthropic.js";
import { TransientError } from "../src/retry.js";

describe("AnthropicProvider", () => {
  it("maps a tool_use response into generic ToolCalls", async () => {
    const create = vi.fn().mockResolvedValue({
      content: [{ type: "tool_use", id: "call_1", name: "report_analysis", input: { a: 1 } }],
    });
    const provider = new AnthropicProvider({ messages: { create } } as never, "claude-sonnet-5-5");

    const result = await provider.chatWithTools({
      messages: [{ role: "user", text: "hi" }],
      tools: [{ name: "report_analysis", description: "d", inputSchema: {} }],
    });

    expect(result.toolCalls).toEqual([{ id: "call_1", name: "report_analysis", input: { a: 1 } }]);
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [{ role: "user", content: "hi" }],
        tools: [{ name: "report_analysis", description: "d", input_schema: {} }],
      }),
    );
  });

  it("converts a 429 API error into a TransientError", async () => {
    const apiError = Object.create(Anthropic.APIError.prototype);
    Object.assign(apiError, { status: 429, message: "rate limited" });
    const create = vi.fn().mockRejectedValue(apiError);
    const provider = new AnthropicProvider({ messages: { create } } as never, "claude-sonnet-5-5");

    await expect(
      provider.chatWithTools({ messages: [{ role: "user", text: "hi" }], tools: [] }),
    ).rejects.toBeInstanceOf(TransientError);
  });

  it("rethrows a non-retryable API error unchanged", async () => {
    const apiError = Object.create(Anthropic.APIError.prototype);
    Object.assign(apiError, { status: 400, message: "bad request" });
    const create = vi.fn().mockRejectedValue(apiError);
    const provider = new AnthropicProvider({ messages: { create } } as never, "claude-sonnet-5-5");

    await expect(
      provider.chatWithTools({ messages: [{ role: "user", text: "hi" }], tools: [] }),
    ).rejects.not.toBeInstanceOf(TransientError);
  });
});
