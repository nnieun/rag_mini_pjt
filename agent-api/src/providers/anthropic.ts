import Anthropic from "@anthropic-ai/sdk";
import { TransientError } from "../retry.js";
import type {
  ChatMessage,
  ChatWithToolsParams,
  ChatWithToolsResult,
  LlmProvider,
  ToolDef,
} from "./types.js";

function toAnthropicTool(tool: ToolDef): Anthropic.Tool {
  return {
    name: tool.name,
    description: tool.description,
    input_schema: tool.inputSchema as Anthropic.Tool.InputSchema,
  };
}

function toAnthropicMessages(messages: ChatMessage[]): Anthropic.MessageParam[] {
  return messages.map((message) => {
    if ("text" in message) {
      return { role: "user", content: message.text };
    }
    if ("toolCalls" in message) {
      return {
        role: "assistant",
        content: message.toolCalls.map((call) => ({
          type: "tool_use" as const,
          id: call.id,
          name: call.name,
          input: call.input,
        })),
      };
    }
    return {
      role: "user",
      content: message.toolResults.map((result) => ({
        type: "tool_result" as const,
        tool_use_id: result.toolCallId,
        content: result.content,
      })),
    };
  });
}

export class AnthropicProvider implements LlmProvider {
  readonly name = "anthropic" as const;

  constructor(
    private readonly client: Pick<Anthropic, "messages">,
    private readonly model: string,
  ) {}

  async chatWithTools(params: ChatWithToolsParams): Promise<ChatWithToolsResult> {
    try {
      const response = await this.client.messages.create({
        model: this.model,
        max_tokens: 1024,
        temperature: params.temperature,
        tools: params.tools.map(toAnthropicTool),
        tool_choice: params.forceToolName
          ? { type: "tool", name: params.forceToolName }
          : undefined,
        messages: toAnthropicMessages(params.messages),
      });

      const toolCalls = response.content
        .filter((block): block is Anthropic.ToolUseBlock => block.type === "tool_use")
        .map((block) => ({ id: block.id, name: block.name, input: block.input }));
      const textBlock = response.content.find(
        (block): block is Anthropic.TextBlock => block.type === "text",
      );

      return { toolCalls, text: textBlock?.text };
    } catch (error) {
      if (error instanceof Anthropic.APIError) {
        const status = error.status ?? 0;
        if (status === 429 || status >= 500) {
          throw new TransientError(error.message, status);
        }
      }
      throw error;
    }
  }
}

export function createAnthropicProvider(
  model: string = process.env.ANTHROPIC_MODEL ?? "claude-sonnet-5-5",
): AnthropicProvider {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new Error("ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.");
  }
  return new AnthropicProvider(new Anthropic({ apiKey }), model);
}

export function createAnthropicJudgeProvider(): AnthropicProvider {
  return createAnthropicProvider(process.env.ANTHROPIC_JUDGE_MODEL ?? "claude-opus-5-5");
}
