import { afterEach, describe, expect, it, vi } from "vitest";
import { createOpenAiProvider } from "../src/providers/openai.js";
import { hasProviderKey } from "../src/providers/index.js";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("hasProviderKey auto-detection when LLM_PROVIDER is unset", () => {
  it("infers anthropic when only ANTHROPIC_API_KEY is set", () => {
    vi.stubEnv("LLM_PROVIDER", "");
    vi.stubEnv("ANTHROPIC_API_KEY", "sk-ant-test");
    vi.stubEnv("OPENAI_API_KEY", "");
    vi.stubEnv("LLM_API_KEY", "");
    expect(hasProviderKey()).toBe(true);
  });

  it("infers openai when only LLM_API_KEY (router) is set", () => {
    vi.stubEnv("LLM_PROVIDER", "");
    vi.stubEnv("ANTHROPIC_API_KEY", "");
    vi.stubEnv("OPENAI_API_KEY", "");
    vi.stubEnv("LLM_API_KEY", "router-key");
    expect(hasProviderKey()).toBe(true);
  });
});

describe("hasProviderKey", () => {
  it("accepts OPENAI_API_KEY for the openai provider", () => {
    vi.stubEnv("LLM_PROVIDER", "openai");
    vi.stubEnv("OPENAI_API_KEY", "sk-test");
    vi.stubEnv("LLM_API_KEY", "");
    expect(hasProviderKey()).toBe(true);
  });

  it("also accepts LLM_API_KEY (OpenAI-compatible router) for the openai provider", () => {
    vi.stubEnv("LLM_PROVIDER", "openai");
    vi.stubEnv("OPENAI_API_KEY", "");
    vi.stubEnv("LLM_API_KEY", "router-key");
    expect(hasProviderKey()).toBe(true);
  });

  it("returns false when no key is set for the selected provider", () => {
    vi.stubEnv("LLM_PROVIDER", "openai");
    vi.stubEnv("OPENAI_API_KEY", "");
    vi.stubEnv("LLM_API_KEY", "");
    expect(hasProviderKey()).toBe(false);
  });
});

describe("createOpenAiProvider", () => {
  it("falls back to LLM_API_KEY/LLM_BASE_URL when OPENAI_* vars are unset", () => {
    vi.stubEnv("OPENAI_API_KEY", "");
    vi.stubEnv("LLM_API_KEY", "router-key");
    vi.stubEnv("LLM_BASE_URL", "https://monogpt.kr/api/monorouter/v1/");

    const provider = createOpenAiProvider();

    expect(provider.name).toBe("openai");
  });

  it("throws when neither OPENAI_API_KEY nor LLM_API_KEY is set", () => {
    vi.stubEnv("OPENAI_API_KEY", "");
    vi.stubEnv("LLM_API_KEY", "");

    expect(() => createOpenAiProvider()).toThrow(/OPENAI_API_KEY|LLM_API_KEY/);
  });
});
