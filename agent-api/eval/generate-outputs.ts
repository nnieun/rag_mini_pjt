import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { analyzeDocument } from "../src/llm.js";
import { createProvider, hasProviderKey } from "../src/providers/index.js";
import { AnalyzeInput } from "../src/schema.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

type DatasetRow = { id: string } & AnalyzeInput & { expected_category: string };

function loadDataset(): DatasetRow[] {
  const raw = readFileSync(join(__dirname, "dataset.jsonl"), "utf-8");
  return raw
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as DatasetRow);
}

async function main() {
  if (!hasProviderKey()) {
    console.log("API 키가 설정되지 않아 출력 생성을 건너뜁니다.");
    return;
  }

  const rows = loadDataset();
  const provider = createProvider();
  const lines: string[] = [];

  for (const row of rows) {
    const input = AnalyzeInput.parse({ text: row.text, fields_to_extract: row.fields_to_extract });
    const output = await analyzeDocument(input, provider);
    lines.push(JSON.stringify({ id: row.id, output }));
    console.log(`[${row.id}] category=${output.classification.category} status=${output.status}`);
  }

  writeFileSync(join(__dirname, "baseline_outputs.jsonl"), lines.join("\n") + "\n", "utf-8");
  console.log(`\n${lines.length}건을 eval/baseline_outputs.jsonl에 저장했습니다.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
