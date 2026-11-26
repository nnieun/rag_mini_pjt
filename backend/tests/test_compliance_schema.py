import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from agents.compliance_schemas import (
    HIGH_IMPACT_CATEGORIES,
    OBLIGATIONS,
    ComplianceAssessment,
    Obligation,
)
from eval.score_compliance import load_cases, score_case, score_predictions

BACKEND = Path(__file__).resolve().parents[1]


def perfect_assessment(case: dict) -> dict:
    expected = case["expected"]
    return {
        "high_impact": "yes" if expected["high_impact"] else "no",
        "high_impact_categories": expected["categories"],
        "obligations": [
            {"article": article, "applies": "해당", "source_ids": ["S1"]}
            for article in expected["obligations"]
        ],
        "confidence": 0.9,
    }


class ComplianceSchemaTest(unittest.TestCase):
    def test_article_id_is_normalized_and_validated(self):
        self.assertEqual(Obligation(article="제 31조 제1항", applies="해당").article, "제31조제1항")
        with self.assertRaises(ValidationError):
            Obligation(article="31조", applies="해당")

    def test_categories_must_exist_in_article_2(self):
        assessment = ComplianceAssessment(
            high_impact="yes", high_impact_categories=["사목", "사"], confidence=0.8
        )
        self.assertEqual(assessment.high_impact_categories, ["사"])
        with self.assertRaises(ValidationError):
            ComplianceAssessment(high_impact="yes", high_impact_categories=["타"], confidence=0.8)

    def test_confidence_range_and_disclaimer(self):
        with self.assertRaises(ValidationError):
            ComplianceAssessment(high_impact="no", confidence=1.5)
        self.assertIn("법률 자문이 아닙니다", ComplianceAssessment(high_impact="no", confidence=0.5).disclaimer)


class ComplianceSetTest(unittest.TestCase):
    def test_set_has_twenty_valid_cases(self):
        cases = load_cases()
        self.assertEqual(len(cases), 20)
        self.assertEqual(len({case["id"] for case in cases}), 20)
        for case in cases:
            expected = case["expected"]
            self.assertTrue(set(expected["categories"]) <= set(HIGH_IMPACT_CATEGORIES), case["id"])
            self.assertTrue(set(expected["obligations"]) <= set(OBLIGATIONS), case["id"])
            self.assertEqual(bool(expected["categories"]), expected["high_impact"], case["id"])
            self.assertIn("제33조제1항", expected["obligations"], case["id"])
            if expected["high_impact"]:
                self.assertIn("제34조제1항", expected["obligations"], case["id"])

    def test_set_covers_every_category_except_decree(self):
        covered = {cat for case in load_cases() for cat in case["expected"]["categories"]}
        self.assertEqual(covered, set(HIGH_IMPACT_CATEGORIES) - {"카"})


class ScoringTest(unittest.TestCase):
    def test_perfect_predictions_pass_gate(self):
        cases = load_cases()
        _, summary = score_predictions(cases, {c["id"]: perfect_assessment(c) for c in cases})
        self.assertEqual(summary["decision_accuracy"], 1.0)
        self.assertEqual(summary["obligation_f1"], 1.0)
        self.assertTrue(summary["gate_passed"])

    def test_wrong_category_or_uncertain_is_wrong_decision(self):
        case = load_cases()[0]  # C01 채용, 사목
        wrong = ComplianceAssessment.model_validate(
            {**perfect_assessment(case), "high_impact_categories": ["가"]}
        )
        uncertain = ComplianceAssessment.model_validate(
            {**perfect_assessment(case), "high_impact": "uncertain"}
        )
        self.assertFalse(score_case(case, wrong).decision_correct)
        self.assertFalse(score_case(case, uncertain).decision_correct)

    def test_obligation_errors_are_counted(self):
        case = load_cases()[0]
        prediction = perfect_assessment(case)
        prediction["obligations"] = prediction["obligations"][1:] + [
            {"article": "제36조제1항", "applies": "해당 가능"},
            {"article": "제32조제1항", "applies": "해당 없음"},
        ]
        score = score_case(case, ComplianceAssessment.model_validate(prediction))
        self.assertEqual((score.false_negative, score.false_positive), (1, 1))
        self.assertEqual(score.extra, ["제36조제1항"])

    def test_missing_prediction_scores_zero(self):
        cases = load_cases()
        _, summary = score_predictions(cases, {})
        self.assertEqual(summary["decision_accuracy"], 0.0)
        self.assertFalse(summary["gate_passed"])

    def test_cli_exit_code_follows_gate(self):
        cases = load_cases()
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pred.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps({"id": c["id"], "assessment": perfect_assessment(c)}, ensure_ascii=False)
                    for c in cases
                ),
                encoding="utf-8",
            )
            done = subprocess.run(
                [sys.executable, "eval/score_compliance.py", "--predictions", str(path), "--json"],
                cwd=BACKEND, capture_output=True, text=True,
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)["gate_passed"])


if __name__ == "__main__":
    unittest.main()
