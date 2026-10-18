import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { computeAgreement, type JudgeHumanPair } from "../src/agreement.js";
import { judgeAnswer } from "../src/judge.js";
import { createJudgeProvider, hasProviderKey } from "../src/providers/index.js";
import { AnalyzeInput, AnalyzeResult, HumanScore } from "../src/schema.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadJsonl<T>(filename: string): T[] {
  const raw = readFileSync(join(__dirname, filename), "utf-8");
  return raw
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as T);
}

type DatasetRow = { id: string } & AnalyzeInput;
type OutputRow = { id: string; output: AnalyzeResult };

async function main() {
  if (!hasProviderKey()) {
    console.log("API 키가 설정되지 않아 judge 평가를 건너뜁니다.");
    return;
  }

  const dataset = loadJsonl<DatasetRow>("dataset.jsonl");
  const outputs = loadJsonl<OutputRow>("baseline_outputs.jsonl");
  const humanScores = loadJsonl<HumanScore>("human_scores.jsonl");

  const judgeProvider = createJudgeProvider();
  const pairs: JudgeHumanPair[] = [];

  for (const row of dataset) {
    const outputRow = outputs.find((o) => o.id === row.id);
    const human = humanScores.find((h) => h.example_id === row.id);
    if (!outputRow || !human) continue;

    const input = AnalyzeInput.parse({ text: row.text, fields_to_extract: row.fields_to_extract });
    const output = AnalyzeResult.parse(outputRow.output);
    const judge = await judgeAnswer(judgeProvider, input, output);
    pairs.push({ exampleId: row.id, judge, human });
    console.log(`[${row.id}] overall_pass=${judge.overall_pass} summary=${judge.summary}`);
  }

  const agreement = computeAgreement(pairs);
  console.log("\n=== LLM 판정자 vs 사람 채점 일치도 ===");
  for (const row of agreement) {
    console.log(
      `${row.criterionId}: agreement=${(row.agreementRate * 100).toFixed(1)}% ` +
        `kappa=${row.cohenKappa.toFixed(2)} n=${row.n}`,
    );
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
