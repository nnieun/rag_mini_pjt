import unittest

from langchain_core.messages import AIMessage

from agents.compliance_graph import ComplianceAgent, validate_citations
from agents.compliance_schemas import ComplianceAssessment
from tests.test_compliance_graph import HIRING, LawPipeline, ScriptedLLM, call

GENERATIVE = "통신사 고객센터에서 요금제 문의에 텍스트로 답하는 생성형 AI 챗봇."


def lookup_33():
    return [AIMessage("", tool_calls=[call("GetArticle", {"article_number": 33}, "c1")])]


def assessment(high="no", confidence=0.9, source_ids=("S1",)):
    return {
        "high_impact": high,
        "high_impact_categories": ["사"] if high == "yes" else [],
        "obligations": [{"article": "제33조제1항", "applies": "해당", "source_ids": list(source_ids)}],
        "confidence": confidence,
    }


class SequencedAssessments:
    def __init__(self, *values):
        self.values = list(values)
        self.prompts = []

    def __call__(self, messages):
        self.prompts.append(messages[-1][1])
        return self.values.pop(0)


class CitationValidationTest(unittest.IsolatedAsyncioTestCase):
    def test_validate_citations(self):
        good = ComplianceAssessment.model_validate(assessment())
        bad = ComplianceAssessment.model_validate(assessment(source_ids=("S9",)))
        self.assertEqual(validate_citations(good, {"S1": {}}), [])
        self.assertEqual(len(validate_citations(bad, {"S1": {}})), 2)

    async def test_invalid_citation_is_retried_once_with_feedback(self):
        sequence = SequencedAssessments(assessment(source_ids=("S7",)), assessment())
        llm = ScriptedLLM(lookup_33(), structured={"ComplianceAssessment": sequence})
        result = await ComplianceAgent(LawPipeline(), llm).start(GENERATIVE)
        self.assertEqual(len(sequence.prompts), 2)
        self.assertIn("S7", sequence.prompts[1])
        self.assertEqual(result["citation_errors"], [])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["review"]["status"], "not_required")

    async def test_errors_after_retry_go_to_review_with_unknown_ids_removed(self):
        sequence = SequencedAssessments(
            assessment(source_ids=("S7",)), assessment(source_ids=("S8", "S1"))
        )
        sequence.values[1]["obligations"].append(
            {"article": "제31조제1항", "applies": "해당", "source_ids": ["S9"]}
        )
        llm = ScriptedLLM(lookup_33(), structured={"ComplianceAssessment": sequence})
        result = await ComplianceAgent(LawPipeline(), llm).start(GENERATIVE)
        self.assertEqual(len(sequence.prompts), 2)
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertIn("근거 인용 오류가 남아 있음", result["review_request"]["reasons"])
        by_article = {o.article: o for o in result["assessment"].obligations}
        self.assertEqual(by_article["제33조제1항"].source_ids, ["S1"])
        self.assertEqual(by_article["제31조제1항"].source_ids, [])


class HumanReviewTest(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, value):
        llm = ScriptedLLM(lookup_33(), structured={"ComplianceAssessment": value})
        agent = ComplianceAgent(LawPipeline(), llm)
        return agent, await agent.start(HIRING, thread_id="t-1")

    async def test_high_impact_waits_for_approval_and_resumes(self):
        agent, started = await self.run_case(assessment(high="yes"))
        self.assertEqual(started["status"], "awaiting_approval")
        self.assertEqual(started["review_request"]["reasons"], ["고영향 인공지능 해당"])
        self.assertIsNone(started["review"])

        done = await agent.resume("t-1", approved=True, reviewer="kim", comment="확인")
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["review"]["status"], "approved")
        self.assertEqual(done["review"]["reviewer"], "kim")
        with self.assertRaises(ValueError):
            await agent.resume("t-1", approved=True)

    async def test_low_confidence_can_be_rejected(self):
        agent, started = await self.run_case(assessment(confidence=0.5))
        self.assertEqual(started["review_request"]["reasons"], ["신뢰도 0.50 < 0.7"])
        rejected = await agent.resume("t-1", approved=False, comment="근거 부족")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["review"]["comment"], "근거 부족")

    async def test_confident_non_high_impact_needs_no_review(self):
        _, result = await self.run_case(assessment())
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(result["review_request"])

    async def test_unknown_thread(self):
        agent = ComplianceAgent(LawPipeline(), ScriptedLLM([]))
        self.assertEqual((await agent.result("nope"))["status"], "not_found")


if __name__ == "__main__":
    unittest.main()
