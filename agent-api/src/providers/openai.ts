import OpenAI from "openai";
import type { ChatCompletionMessageParam, ChatCompletionTool } from "openai/resources/index.js";
import { TransientError } from "../retry.js";
import type {
  ChatMessage,
  ChatWithToolsParams,
  ChatWithToolsResult,
  LlmProvider,
  ToolDef,
} from "./types.js";

function toOpenAiTool(tool: ToolDef): ChatCompletionTool {
  return {
    type: "function",
    function: {
      name: tool.name,
      description: tool.description,
      parameters: tool.inputSchema,
    },
  };
}

function toOpenAiMessages(messages: ChatMessage[]): ChatCompletionMessageParam[] {
  const result: ChatCompletionMessageParam[] = [];
  for (const message of messages) {
    if ("text" in message) {
      result.push({ role: "user", content: message.text });
      continue;
    }
    if ("toolCalls" in message) {
      result.push({
        role: "assistant",
        content: null,
        tool_calls: message.toolCalls.map((call) => ({
          id: call.id,
          type: "function",
          function: { name: call.name, arguments: JSON.stringify(call.input) },
        })),
      });
      continue;
    }
    for (const toolResult of message.toolResults) {
      result.push({
        role: "tool",
        tool_call_id: toolResult.toolCallId,
        content: toolResult.content,
      });
    }
  }
  return result;
}

export class OpenAiProvider implements LlmProvider {
  readonly name = "openai" as const;

  constructor(
    private readonly client: Pick<OpenAI, "chat">,
    private readonly model: string,
  ) {}

  async chatWithTools(params: ChatWithToolsParams): Promise<ChatWithToolsResult> {
    try {
      const response = await this.client.chat.completions.create({
        model: this.model,
        temperature: params.temperature,
        tools: params.tools.map(toOpenAiTool),
        tool_choice: params.forceToolName
          ? { type: "function", function: { name: params.forceToolName } }
          : undefined,
        messages: toOpenAiMessages(params.messages),
      });

      const message = response.choices[0]?.message;
      const toolCalls = (message?.tool_calls ?? [])
        .filter((call) => call.type === "function")
        .map((call) => ({
          id: call.id,
          name: call.function.name,
          input: JSON.parse(call.function.arguments || "{}"),
        }));

      return { toolCalls, text: message?.content ?? undefined };
    } catch (error) {
      if (error instanceof OpenAI.APIError) {
        const status = error.status ?? 0;
        if (status === 429 || status >= 500) {
          throw new TransientError(error.message, status);
        }
      }
      throw error;
    }
  }
}

export function createOpenAiProvider(
  model: string = process.env.OPENAI_MODEL ?? "gpt-4o-mini",
): OpenAiProvider {
  // OPENAI_API_KEY가 있으면 공식 OpenAI 엔드포인트를 쓴다(OPENAI_BASE_URL로만 override 가능).
  // OPENAI_API_KEY가 없을 때만 LLM_API_KEY/LLM_BASE_URL(monogpt 등 호환 게이트웨이, backend/.env.example과
  // 동일한 네이밍)로 폴백한다. 두 키·URL을 섞어 쓰면 "OpenAI 키로 monogpt를 호출"하는 오조합이 생기므로 분리한다.
  const usingOfficialOpenAi = Boolean(process.env.OPENAI_API_KEY);
  const apiKey = process.env.OPENAI_API_KEY || process.env.LLM_API_KEY;
  const baseURL = usingOfficialOpenAi
    ? process.env.OPENAI_BASE_URL
    : process.env.OPENAI_BASE_URL || process.env.LLM_BASE_URL;
  if (!apiKey) {
    throw new Error("OPENAI_API_KEY 또는 LLM_API_KEY 환경 변수가 설정되지 않았습니다.");
  }
  return new OpenAiProvider(new OpenAI({ apiKey, baseURL }), model);
}

export function createOpenAiJudgeProvider(): OpenAiProvider {
  return createOpenAiProvider(process.env.OPENAI_JUDGE_MODEL ?? "gpt-4o");
}
