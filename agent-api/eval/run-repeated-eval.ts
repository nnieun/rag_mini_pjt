import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { analyzeDocument } from "../src/llm.js";
import { judgeAnswer } from "../src/judge.js";
import { createJudgeProvider, createProvider, hasProviderKey } from "../src/providers/index.js";
import { compareBinaryRates } from "../src/repeated.js";
import { AnalyzeInput } from "../src/schema.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPEATS = Number(process.env.EVAL_REPEATS ?? 8);

// LLM 출력은 temperature > 0에서 매번 달라질 수 있다. 같은 입력을 N회 반복 실행해
// "개선 전/후" 프롬프트의 overall_pass 비율을 비교하고, 그 차이가 반복 측정의 노이즈
// 범위를 넘어서는 통계적으로 의미 있는 개선인지 확인한다.
const IMPROVED_INSTRUCTION =
  "원문에 명시적으로 존재하지 않는 내용은 절대 추론하지 말고 value를 null, " +
  "해당 필드명을 missing_fields에 넣어라. source_quote는 원문에서 그대로 복사해야 한다.";

async function main() {
  if (!hasProviderKey()) {
    console.log("API 키가 설정되지 않아 반복 측정 평가를 건너뜁니다.");
    return;
  }

  const [exampleRaw] = readFileSync(join(__dirname, "dataset.jsonl"), "utf-8")
    .split("\n")
    .filter((line) => line.trim().length > 0);
  const example = JSON.parse(exampleRaw) as { text: string; fields_to_extract: string[] };
  const input = AnalyzeInput.parse(example);

  const provider = createProvider();
  const judgeProvider = createJudgeProvider();

  async function runVariant(extraInstruction?: string): Promise<boolean[]> {
    const passes: boolean[] = [];
    for (let i = 0; i < REPEATS; i++) {
      const result = await analyzeDocument(input, provider, { temperature: 1, extraInstruction });
      const verdict = await judgeAnswer(judgeProvider, input, result);
      passes.push(verdict.overall_pass);
    }
    return passes;
  }

  console.log(`baseline 프롬프트 ${REPEATS}회 반복 실행 중...`);
  const before = await runVariant(undefined);
  console.log(`개선 프롬프트 ${REPEATS}회 반복 실행 중...`);
  const after = await runVariant(IMPROVED_INSTRUCTION);

  const comparison = compareBinaryRates(before, after);
  console.log("\n=== 반복 측정 비교 (같은 입력, temperature=1) ===");
  console.log(
    `before: passRate=${(comparison.before.passRate * 100).toFixed(1)}% ` +
      `95% CI=[${(comparison.before.wilsonCi95[0] * 100).toFixed(1)}%, ${(comparison.before.wilsonCi95[1] * 100).toFixed(1)}%] n=${comparison.before.n}`,
  );
  console.log(
    `after:  passRate=${(comparison.after.passRate * 100).toFixed(1)}% ` +
      `95% CI=[${(comparison.after.wilsonCi95[0] * 100).toFixed(1)}%, ${(comparison.after.wilsonCi95[1] * 100).toFixed(1)}%] n=${comparison.after.n}`,
  );
  console.log(
    `diff=${(comparison.diff * 100).toFixed(1)}pt, z=${comparison.zStat.toFixed(2)}, ` +
      `p=${comparison.pValue.toFixed(3)}, significant(p<0.05)=${comparison.significantAt05}`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
