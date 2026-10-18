export type JsonSchema = Record<string, unknown>;

export type ToolDef = {
  name: string;
  description: string;
  inputSchema: JsonSchema;
};

export type ToolCall = {
  id: string;
  name: string;
  input: unknown;
};

export type ChatMessage =
  | { role: "user"; text: string }
  | { role: "assistant"; toolCalls: ToolCall[] }
  | { role: "user"; toolResults: Array<{ toolCallId: string; content: string }> };

export type ChatWithToolsParams = {
  messages: ChatMessage[];
  tools: ToolDef[];
  forceToolName?: string;
  temperature?: number;
};

export type ChatWithToolsResult = {
  toolCalls: ToolCall[];
  text?: string;
};

export type ProviderName = "anthropic" | "openai";

export interface LlmProvider {
  readonly name: ProviderName;
  chatWithTools(params: ChatWithToolsParams): Promise<ChatWithToolsResult>;
}
