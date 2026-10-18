import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { classifyByKeyword } from "../src/baseline.js";
import { analyzeDocument } from "../src/llm.js";
import { createProvider, hasProviderKey } from "../src/providers/index.js";
import { DocumentCategory } from "../src/schema.js";

const PROVIDER_NAME = process.env.LLM_PROVIDER === "openai" ? "openai" : "anthropic";

type EvalRow = {
  text: string;
  fields_to_extract: string[];
  expected_category: DocumentCategory;
};

const __dirname = dirname(fileURLToPath(import.meta.url));

function loadDataset(): EvalRow[] {
  const raw = readFileSync(join(__dirname, "dataset.jsonl"), "utf-8");
  return raw
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .map((line) => JSON.parse(line) as EvalRow);
}

async function runBaseline(rows: EvalRow[]) {
  let correct = 0;
  const started = Date.now();
  for (const row of rows) {
    if (classifyByKeyword(row.text) === row.expected_category) correct += 1;
  }
  return { accuracy: correct / rows.length, elapsedMs: Date.now() - started };
}

async function runLlm(rows: EvalRow[]) {
  const provider = createProvider();
  let correct = 0;
  const started = Date.now();
  for (const row of rows) {
    const result = await analyzeDocument(
      { text: row.text, fields_to_extract: row.fields_to_extract },
      provider,
    );
    if (result.classification.category === row.expected_category) correct += 1;
  }
  return { accuracy: correct / rows.length, elapsedMs: Date.now() - started };
}

async function main() {
  const rows = loadDataset();
  const baseline = await runBaseline(rows);
  console.log(
    `[baseline/keyword] accuracy=${(baseline.accuracy * 100).toFixed(1)}% elapsed=${baseline.elapsedMs}ms n=${rows.length}`,
  );

  if (!hasProviderKey()) {
    console.log(`[llm/${PROVIDER_NAME}] API 키가 설정되지 않아 LLM 평가를 건너뜁니다.`);
    return;
  }
  const llm = await runLlm(rows);
  console.log(
    `[llm/${PROVIDER_NAME}] accuracy=${(llm.accuracy * 100).toFixed(1)}% elapsed=${llm.elapsedMs}ms n=${rows.length}`,
  );
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
