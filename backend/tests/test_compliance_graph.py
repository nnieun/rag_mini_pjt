import unittest
from types import SimpleNamespace

from langchain_core.messages import AIMessage

from agents.compliance_graph import (
    MAX_TOOL_CALLS,
    ComplianceAgent,
    register_sources,
    rule_based_assessment,
)
from agents.compliance_schemas import ServiceProfile
from common.telemetry import RequestTrace, trace_scope

ARTICLES = {
    2: [{"chunk_id": "a2-4", "article": "제2조", "paragraph": "", "item": "제4호", "title": "정의",
         "content": "고영향 인공지능 ... 사. 채용, 대출 심사 등 개인의 권리ㆍ의무 관계에 중대한 영향을 미치는 판단 또는 평가"}],
    31: [{"chunk_id": "a31-1", "article": "제31조", "paragraph": "①", "item": "", "title": "인공지능 투명성 확보 의무",
          "content": "사전에 고지하여야 한다."}],
    33: [{"chunk_id": "a33-1", "article": "제33조", "paragraph": "①", "item": "", "title": "고영향 인공지능의 확인",
          "content": "사전에 검토하여야 하며"}],
    34: [{"chunk_id": "a34-1", "article": "제34조", "paragraph": "①", "item": "", "title": "고영향 인공지능과 관련한 사업자의 책무",
          "content": "다음 각 호의 내용을 포함하는 조치를"}],
    35: [{"chunk_id": "a35-1", "article": "제35조", "paragraph": "①", "item": "", "title": "고영향 인공지능 영향평가",
          "content": "영향을 평가하기 위하여 노력하여야 한다."}],
}


class LawPipeline:
    def __init__(self):
        chunks = {doc["chunk_id"]: doc for docs in ARTICLES.values() for doc in docs}
        self.retriever = SimpleNamespace(chunks_by_key=chunks)
        self.llm = None
        self.queries = []

    async def retrieve(self, query, *, k=5, use_reranking=False):
        self.queries.append(query)
        return ARTICLES[2] + ARTICLES[34]


class ScriptedLLM:
    """bind_tools() returns scripted AIMessages; with_structured_output() returns scripted objects."""

    def __init__(self, turns, structured=None, fail_structured=()):
        self.turns = list(turns)
        self.structured = structured or {}
        self.fail_structured = set(fail_structured)
        self.agent_inputs = []

    def bind_tools(self, tools):
        self.bound = [tool.__name__ for tool in tools]
        return self

    async def ainvoke(self, messages):
        self.agent_inputs.append(list(messages))
        if not self.turns:
            return AIMessage("조사 완료")
        return self.turns.pop(0)

    def with_structured_output(self, schema):
        llm = self

        class Runner:
            async def ainvoke(self, messages):
                if schema.__name__ in llm.fail_structured:
                    raise RuntimeError("structured output failed")
                value = llm.structured.get(schema.__name__)
                if callable(value):
                    return value(messages)
                return value if value is not None else schema()

        return Runner()


def call(name, args, call_id):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


HIRING = "이력서를 읽고 지원자 점수를 매기는 채용 보조 AI. 국내 HR 기업이 개발해 인사팀에 제공한다."


def hiring_assessment(messages):
    evidence = messages[-1][1]
    assert "[S1]" in evidence, evidence
    return {
        "high_impact": "yes",
        "high_impact_categories": ["사"],
        "obligations": [
            {"article": "제33조제1항", "applies": "해당", "source_ids": ["S3"]},
            {"article": "제34조제1항", "applies": "해당", "source_ids": ["S2"]},
        ],
        "confidence": 0.85,
    }


class ComplianceGraphTest(unittest.IsolatedAsyncioTestCase):
    async def test_parallel_tool_calls_then_assessment(self):
        llm = ScriptedLLM(
            [
                AIMessage("", tool_calls=[
                    call("SearchLaw", {"query": "채용 고영향 인공지능"}, "c1"),
                    call("GetArticle", {"article_number": 33}, "c2"),
                ]),
                AIMessage("", tool_calls=[call("GetArticle", {"article_number": 34}, "c3")]),
                AIMessage("조사 완료"),
            ],
            structured={
                "ServiceProfile": {"name": "채용 보조", "domains": ["채용"], "decides_about_individuals": True},
                "ComplianceAssessment": hiring_assessment,
            },
        )
        pipeline = LawPipeline()
        trace = RequestTrace(endpoint="test")
        with trace_scope(trace):
            result = await ComplianceAgent(pipeline, llm).assess(HIRING)

        self.assertEqual(llm.bound, ["SearchLaw", "GetArticle"])
        self.assertEqual(result["method"], "llm")
        self.assertEqual(result["assessment"].high_impact_categories, ["사"])
        # S1=제2조, S2=제34조(검색), S3=제33조; 제34조는 GetArticle로 다시 와도 같은 id
        self.assertEqual(set(result["sources"]), {"S1", "S2", "S3"})
        self.assertEqual(result["tool_trace"][2]["source_ids"], ["S2"])
        self.assertEqual([c["channel"] for c in trace.tool_calls], ["agent"] * 3)
        # 두 번째 agent 호출은 첫 번째 도구 결과 두 개를 모두 본다.
        tool_replies = [m for m in llm.agent_inputs[1] if m.type == "tool"]
        self.assertEqual(len(tool_replies), 2)

    async def test_tool_call_budget_is_enforced(self):
        many = [
            AIMessage("", tool_calls=[call("GetArticle", {"article_number": 33}, f"c{i}-{j}") for j in range(3)])
            for i in range(5)
        ]
        llm = ScriptedLLM(many, structured={"ComplianceAssessment": {"high_impact": "no", "confidence": 0.5}})
        result = await ComplianceAgent(LawPipeline(), llm).assess(HIRING)
        statuses = [item["status"] for item in result["tool_trace"]]
        self.assertEqual(statuses.count("ok"), MAX_TOOL_CALLS)
        self.assertEqual(statuses.count("skipped"), 1)  # 3번째 턴의 9번째 호출
        self.assertEqual(len(llm.agent_inputs), 3)  # 상한 도달 후 agent는 LLM을 부르지 않음

    async def test_unknown_tool_and_tool_error_are_reported_to_llm(self):
        llm = ScriptedLLM(
            [AIMessage("", tool_calls=[
                call("CreatePdf", {}, "x1"),
                call("GetArticle", {"article_number": 0}, "x2"),
            ])],
            structured={"ComplianceAssessment": {"high_impact": "no", "confidence": 0.5}},
        )
        result = await ComplianceAgent(LawPipeline(), llm).assess(HIRING)
        self.assertEqual([t["status"] for t in result["tool_trace"]], ["rejected", "error"])
        replies = [m.content for m in llm.agent_inputs[1] if m.type == "tool"]
        self.assertIn("사용할 수 없는 도구", replies[0])
        self.assertIn("도구 오류", replies[1])

    async def test_falls_back_to_rules_when_llm_assessment_fails(self):
        llm = ScriptedLLM(
            [AIMessage("", tool_calls=[call("GetArticle", {"article_number": 33}, "c1")])],
            structured={"ServiceProfile": {"domains": ["채용"], "is_generative": False}},
            fail_structured={"ComplianceAssessment"},
        )
        result = await ComplianceAgent(LawPipeline(), llm).assess(HIRING)
        assessment = result["assessment"]
        self.assertEqual(result["method"], "rule")
        self.assertEqual((assessment.high_impact, assessment.high_impact_categories), ("yes", ["사"]))
        by_article = {item.article: item for item in assessment.obligations}
        self.assertEqual(by_article["제33조제1항"].source_ids, ["S1"])

    async def test_short_description_is_rejected(self):
        with self.assertRaises(ValueError):
            await ComplianceAgent(LawPipeline(), ScriptedLLM([])).assess("짧음")


class HelpersTest(unittest.TestCase):
    def test_register_sources_reuses_ids(self):
        added, ids = register_sources({}, ARTICLES[33] + ARTICLES[34])
        self.assertEqual(ids, ["S1", "S2"])
        again, ids = register_sources(added, ARTICLES[34] + ARTICLES[35])
        self.assertEqual(ids, ["S2", "S3"])
        self.assertEqual(list(again), ["S3"])

    def test_rule_based_generative_service(self):
        profile = ServiceProfile(
            summary="고객 문의에 답하는 생성형 챗봇", is_generative=True,
            generates_realistic_media=False, large_training_compute=False, has_domestic_presence=True,
        )
        assessment = rule_based_assessment(profile, {}, "통신사 고객센터 챗봇")
        self.assertEqual(assessment.high_impact, "no")
        self.assertEqual(
            assessment.applicable_articles(), {"제31조제1항", "제31조제2항", "제33조제1항"}
        )


if __name__ == "__main__":
    unittest.main()
