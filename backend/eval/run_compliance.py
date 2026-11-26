"""Run the compliance agent on eval/compliance_set.jsonl and score it.

    # 실제 Qdrant·LLM으로 (M3 게이트 확인)
    uv run python eval/run_compliance.py --out eval/results/compliance_predictions.jsonl

    # LLM 없이 키워드 규칙 기준선만
    uv run python eval/run_compliance.py --rule-baseline --out /tmp/rule.jsonl
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.compliance_graph import ComplianceAgent, rule_based_assessment  # noqa: E402
from agents.compliance_schemas import ServiceProfile  # noqa: E402
from eval.score_compliance import (  # noqa: E402
    DEFAULT_SET,
    load_cases,
    markdown_report,
    score_predictions,
)


async def predict(cases: list[dict], rule_baseline: bool) -> dict[str, dict]:
    predictions: dict[str, dict] = {}
    if rule_baseline:
        for case in cases:
            assessment = rule_based_assessment(ServiceProfile(), {}, case["description"])
            predictions[case["id"]] = assessment.model_dump()
        return predictions

    from rag.pipeline import RAGPipeline

    pipeline = RAGPipeline.create_default()
    agent = ComplianceAgent(pipeline)
    try:
        for case in cases:
            result = await agent.assess(case["description"])
            predictions[case["id"]] = result["assessment"].model_dump()
            print(f"{case['id']} {result['method']} tools={len(result['tool_trace'])}", file=sys.stderr)
    finally:
        pipeline.close()
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=str(DEFAULT_SET))
    parser.add_argument("--out", required=True)
    parser.add_argument("--rule-baseline", action="store_true")
    args = parser.parse_args()
    cases = load_cases(args.cases)
    predictions = asyncio.run(predict(cases, args.rule_baseline))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as file:
        for case_id, assessment in predictions.items():
            file.write(json.dumps({"id": case_id, "assessment": assessment}, ensure_ascii=False) + "\n")
    scores, summary = score_predictions(cases, predictions)
    print(markdown_report(scores, summary))


if __name__ == "__main__":
    main()
