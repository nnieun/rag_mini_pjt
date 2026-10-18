import { createAnthropicJudgeProvider, createAnthropicProvider } from "./anthropic.js";
import { createOpenAiJudgeProvider, createOpenAiProvider } from "./openai.js";
import type { LlmProvider, ProviderName } from "./types.js";

export * from "./types.js";

function resolveProviderName(explicit?: ProviderName): ProviderName {
  if (explicit) return explicit;
  const fromEnv = process.env.LLM_PROVIDER;
  if (fromEnv === "openai" || fromEnv === "anthropic") return fromEnv;

  // LLM_PROVIDER가 명시되지 않으면 어떤 키가 채워져 있는지로 추론한다.
  // (예: backend/.env에는 LLM_PROVIDER가 없고 LLM_API_KEY/LLM_BASE_URL만 있는 경우)
  const hasAnthropicKey = Boolean(process.env.ANTHROPIC_API_KEY);
  const hasOpenAiKey = Boolean(process.env.OPENAI_API_KEY || process.env.LLM_API_KEY);
  if (hasAnthropicKey && !hasOpenAiKey) return "anthropic";
  if (hasOpenAiKey && !hasAnthropicKey) return "openai";
  return "anthropic";
}

export function createProvider(name?: ProviderName): LlmProvider {
  return resolveProviderName(name) === "openai" ? createOpenAiProvider() : createAnthropicProvider();
}

export function createJudgeProvider(name?: ProviderName): LlmProvider {
  return resolveProviderName(name) === "openai"
    ? createOpenAiJudgeProvider()
    : createAnthropicJudgeProvider();
}

export function hasProviderKey(name?: ProviderName): boolean {
  if (resolveProviderName(name) === "openai") {
    return Boolean(process.env.OPENAI_API_KEY || process.env.LLM_API_KEY);
  }
  return Boolean(process.env.ANTHROPIC_API_KEY);
}
