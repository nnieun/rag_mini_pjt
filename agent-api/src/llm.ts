import {
  AnalyzeInput,
  AnalyzeResult,
  ClassificationResult,
  ExtractionResult,
} from "./schema.js";
import { withRetry } from "./retry.js";
import { ALLOWED_TOOLS, executeLookupGlossary, lookupGlossaryTool } from "./tools.js";
import type { ChatMessage, LlmProvider, ToolDef } from "./providers/types.js";
import { createProvider } from "./providers/index.js";

const MAX_TOOL_ROUNDS = 4;

const reportAnalysisTool: ToolDef = {
  name: "report_analysis",
  description: "문서 분류와 정보 추출 결과를 구조화된 형식으로 보고한다.",
  inputSchema: {
    type: "object",
    properties: {
      category: {
        type: "string",
        enum: ["contract", "invoice", "support_request", "report", "other"],
      },
      confidence: { type: "number" },
      reason: { type: "string" },
      fields: {
        type: "array",
        items: {
          type: "object",
          properties: {
            name: { type: "string" },
            value: { type: ["string", "null"] },
            source_quote: { type: ["string", "null"] },
          },
          required: ["name", "value", "source_quote"],
        },
      },
      missing_fields: { type: "array", items: { type: "string" } },
    },
    required: ["category", "confidence", "reason", "fields", "missing_fields"],
  },
};

export type AnalyzeOptions = {
  temperature?: number;
  extraInstruction?: string;
};

export async function analyzeDocument(
  input: AnalyzeInput,
  provider: LlmProvider,
  options: AnalyzeOptions = {},
): Promise<AnalyzeResult> {
  const parsedInput = AnalyzeInput.parse(input);
  const errors: string[] = [];

  const messages: ChatMessage[] = [
    {
      role: "user",
      text:
        `다음 문서를 분류하고 요청된 필드를 추출하라.\n` +
        `추출할 필드: ${parsedInput.fields_to_extract.join(", ")}\n` +
        `모르는 약어가 있으면 lookup_glossary를 호출하라.\n` +
        (options.extraInstruction ? `${options.extraInstruction}\n` : "") +
        `\n문서:\n"""\n${parsedInput.text}\n"""`,
    },
  ];

  for (let round = 0; round < MAX_TOOL_ROUNDS; round++) {
    const response = await withRetry(() =>
      provider.chatWithTools({
        messages,
        tools: [lookupGlossaryTool, reportAnalysisTool],
        temperature: options.temperature,
      }),
    );

    const report = response.toolCalls.find((call) => call.name === "report_analysis");
    if (report) {
      return buildResult(report.input, errors);
    }

    const glossaryCalls = response.toolCalls.filter((call) => ALLOWED_TOOLS.has(call.name));
    if (glossaryCalls.length === 0) {
      errors.push("모델이 report_analysis를 호출하지 않았습니다.");
      break;
    }

    messages.push({ role: "assistant", toolCalls: response.toolCalls });
    messages.push({
      role: "user",
      toolResults: glossaryCalls.map((call) => ({
        toolCallId: call.id,
        content: executeLookupGlossary(call.input as { term: string }),
      })),
    });
  }

  return {
    classification: { category: "other", confidence: 0, reason: "분석 실패" },
    extraction: { fields: [], missing_fields: parsedInput.fields_to_extract },
    status: "failed",
    errors: errors.length > 0 ? errors : ["최대 도구 호출 라운드를 초과했습니다."],
  };
}

function buildResult(rawInput: unknown, errors: string[]): AnalyzeResult {
  const input = rawInput as Record<string, unknown>;
  const classificationParsed = ClassificationResult.safeParse({
    category: input.category,
    confidence: input.confidence,
    reason: input.reason,
  });
  const extractionParsed = ExtractionResult.safeParse({
    fields: input.fields,
    missing_fields: input.missing_fields,
  });

  if (!classificationParsed.success) {
    errors.push(`classification 검증 실패: ${classificationParsed.error.message}`);
  }
  if (!extractionParsed.success) {
    errors.push(`extraction 검증 실패: ${extractionParsed.error.message}`);
  }

  const status: AnalyzeResult["status"] =
    errors.length > 0 ? "failed" : (extractionParsed.data?.missing_fields.length ?? 0) > 0 ? "needs_review" : "ok";

  return {
    classification:
      classificationParsed.data ?? { category: "other", confidence: 0, reason: "검증 실패" },
    extraction: extractionParsed.data ?? { fields: [], missing_fields: [] },
    status,
    errors,
  };
}

export { createProvider };
export type { LlmProvider };
