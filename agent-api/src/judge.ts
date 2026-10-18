import { withRetry } from "./retry.js";
import { AnalyzeInput, AnalyzeResult, JudgeVerdict } from "./schema.js";
import { RUBRIC, buildRubricText } from "./rubric.js";
import type { ChatMessage, LlmProvider, ToolDef } from "./providers/types.js";
import { createJudgeProvider } from "./providers/index.js";

const submitJudgmentTool: ToolDef = {
  name: "submit_judgment",
  description: "루브릭 기준별 채점 결과를 제출한다.",
  inputSchema: {
    type: "object",
    properties: {
      criteria: {
        type: "array",
        items: {
          type: "object",
          properties: {
            criterion_id: { type: "string" },
            score: { type: "integer", enum: [0, 1] },
            rationale: { type: "string" },
          },
          required: ["criterion_id", "score", "rationale"],
        },
      },
      overall_pass: { type: "boolean" },
      summary: { type: "string" },
    },
    required: ["criteria", "overall_pass", "summary"],
  },
};

export async function judgeAnswer(
  provider: LlmProvider,
  input: AnalyzeInput,
  output: AnalyzeResult,
): Promise<JudgeVerdict> {
  const parsedInput = AnalyzeInput.parse(input);
  const prompt =
    `아래 루브릭에 따라 AI의 문서 분류·추출 결과를 채점하라. 각 기준마다 0(미달) 또는 1(충족)로 점수를 매기고, ` +
    `구체적인 이유를 1문장 이상 적어라. 추측하지 말고 원문과 결과만 근거로 판단하라.\n\n` +
    `루브릭:\n${buildRubricText()}\n\n` +
    `원문:\n"""\n${parsedInput.text}\n"""\n\n` +
    `추출 요청 필드: ${parsedInput.fields_to_extract.join(", ")}\n\n` +
    `AI 결과:\n${JSON.stringify(output, null, 2)}`;

  const messages: ChatMessage[] = [{ role: "user", text: prompt }];

  const response = await withRetry(() =>
    provider.chatWithTools({
      messages,
      tools: [submitJudgmentTool],
      forceToolName: "submit_judgment",
    }),
  );

  const toolUse = response.toolCalls.find((call) => call.name === "submit_judgment");
  if (!toolUse) {
    throw new Error("판정자가 submit_judgment를 호출하지 않았습니다.");
  }

  const rawInput = toolUse.input as Record<string, unknown>;
  const knownIds = new Set(RUBRIC.map((c) => c.id));
  const criteria = Array.isArray(rawInput.criteria)
    ? (rawInput.criteria as Array<Record<string, unknown>>).filter((c) =>
        knownIds.has(String(c.criterion_id)),
      )
    : [];

  return JudgeVerdict.parse({ ...rawInput, criteria });
}

export { createJudgeProvider };
