"""Score compliance-agent predictions against eval/compliance_set.jsonl.

    uv run python eval/score_compliance.py --predictions eval/results/compliance_predictions.jsonl

Predictions file: one JSON object per line, `{"id": "C01", "assessment": {...}}`,
where `assessment` is a `ComplianceAssessment`.

Metrics
- decision accuracy (M3 gate, 85%): high-impact verdict is right, and for
  high-impact cases at least one expected category (제2조제4호 목) is predicted.
  "uncertain" counts as wrong.
- category exact match: predicted category set equals the label.
- obligations: micro precision / recall / F1 over article ids marked
  "해당" or "해당 가능".
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.compliance_schemas import ComplianceAssessment  # noqa: E402

DEFAULT_SET = Path(__file__).resolve().parent / "compliance_set.jsonl"
GATE = 0.85


def load_jsonl(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def load_cases(path: str | Path = DEFAULT_SET) -> list[dict]:
    return load_jsonl(path)


@dataclass
class CaseScore:
    case_id: str
    decision_correct: bool
    category_exact: bool
    true_positive: int
    false_positive: int
    false_negative: int
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)


def score_case(case: dict, assessment: ComplianceAssessment | None) -> CaseScore:
    expected = case["expected"]
    expected_obligations = set(expected["obligations"])
    if assessment is None:
        return CaseScore(case["id"], False, False, 0, 0, len(expected_obligations),
                         missing=sorted(expected_obligations))
    predicted_high = {"yes": True, "no": False}.get(assessment.high_impact)
    categories = set(assessment.high_impact_categories)
    expected_categories = set(expected["categories"])
    decision = predicted_high is expected["high_impact"] and (
        not expected["high_impact"] or bool(categories & expected_categories)
    )
    predicted = assessment.applicable_articles()
    return CaseScore(
        case_id=case["id"],
        decision_correct=decision,
        category_exact=categories == expected_categories,
        true_positive=len(predicted & expected_obligations),
        false_positive=len(predicted - expected_obligations),
        false_negative=len(expected_obligations - predicted),
        missing=sorted(expected_obligations - predicted),
        extra=sorted(predicted - expected_obligations),
    )


def summarize(scores: list[CaseScore]) -> dict[str, float]:
    total = len(scores) or 1
    tp = sum(score.true_positive for score in scores)
    fp = sum(score.false_positive for score in scores)
    fn = sum(score.false_negative for score in scores)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = sum(score.decision_correct for score in scores) / total
    return {
        "cases": len(scores),
        "decision_accuracy": round(accuracy, 4),
        "category_exact": round(sum(score.category_exact for score in scores) / total, 4),
        "obligation_precision": round(precision, 4),
        "obligation_recall": round(recall, 4),
        "obligation_f1": round(f1, 4),
        "gate_passed": accuracy >= GATE,
    }


def score_predictions(cases: list[dict], predictions: dict[str, dict]) -> tuple[list[CaseScore], dict]:
    scores = []
    for case in cases:
        raw = predictions.get(case["id"])
        assessment = ComplianceAssessment.model_validate(raw) if raw is not None else None
        scores.append(score_case(case, assessment))
    return scores, summarize(scores)


def markdown_report(scores: list[CaseScore], summary: dict) -> str:
    lines = [
        "| 지표 | 값 |",
        "|---|---|",
        f"| 문항 수 | {summary['cases']} |",
        f"| 판정 정확도 (게이트 {GATE:.0%}) | {summary['decision_accuracy']:.1%} "
        f"{'통과' if summary['gate_passed'] else '미달'} |",
        f"| 목 정확 일치 | {summary['category_exact']:.1%} |",
        f"| 의무 Precision / Recall / F1 | {summary['obligation_precision']:.2f} / "
        f"{summary['obligation_recall']:.2f} / {summary['obligation_f1']:.2f} |",
        "",
        "| 문항 | 판정 | 누락 의무 | 과잉 의무 |",
        "|---|---|---|---|",
    ]
    for score in scores:
        lines.append(
            f"| {score.case_id} | {'O' if score.decision_correct else 'X'} | "
            f"{', '.join(score.missing) or '-'} | {', '.join(score.extra) or '-'} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="컴플라이언스 에이전트 예측 채점")
    parser.add_argument("--cases", default=str(DEFAULT_SET))
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--json", action="store_true", help="요약을 JSON으로 출력")
    args = parser.parse_args()
    predictions = {row["id"]: row["assessment"] for row in load_jsonl(args.predictions)}
    scores, summary = score_predictions(load_cases(args.cases), predictions)
    print(json.dumps(summary, ensure_ascii=False) if args.json else markdown_report(scores, summary))
    sys.exit(0 if summary["gate_passed"] else 1)


if __name__ == "__main__":
    main()
