from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rag.graph import LangGraphRAG, select_tool_by_llm, select_tool_by_rule
from rag.schemas import RequestAnalysis
from tests.test_agentic_features import AgenticFakePipeline


class FakeBoundLLM:
    def __init__(self, tool_calls=None, error=None):
        self.tool_calls = tool_calls or []
        self.error = error
        self.inputs = []

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.inputs.append(messages)
        if self.error:
            raise self.error
        return SimpleNamespace(tool_calls=self.tool_calls)


class RuleSelectionTest(unittest.TestCase):
    def test_pdf_request_routes_to_create_pdf(self):
        name, args = select_tool_by_rule(
            "방금 답변 PDF로 줘", "방금 답변 PDF로 줘", "방금 답변 PDF로 줘", RequestAnalysis()
        )
        self.assertEqual(name, "CreatePdf")
        self.assertTrue(args["include_sources"])

    def test_article_number_routes_to_get_article(self):
        name, args = select_tool_by_rule(
            "제33조 알려줘", "제33조 알려줘", "제33조", RequestAnalysis(article_number=33)
        )
        self.assertEqual((name, args), ("GetArticle", {"article_number": 33}))

    def test_list_query_expands_top_k(self):
        name, args = select_tool_by_rule(
            "관련 조문 전부 알려줘", "관련 조문 전부 알려줘", "관련 조문", RequestAnalysis()
        )
        self.assertEqual(name, "SearchLaw")
        self.assertEqual(args["top_k"], 20)


class LlmSelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_llm_choice_is_used(self):
        llm = FakeBoundLLM([{"name": "GetArticle", "args": {"article_number": 2}}])
        self.assertEqual(
            await select_tool_by_llm(llm, "정의 조문"), ("GetArticle", {"article_number": 2})
        )

    async def test_unknown_tool_falls_back(self):
        llm = FakeBoundLLM([{"name": "DeleteEverything", "args": {}}])
        self.assertIsNone(await select_tool_by_llm(llm, "질문"))

    async def test_llm_error_or_no_call_falls_back(self):
        self.assertIsNone(await select_tool_by_llm(FakeBoundLLM(error=RuntimeError()), "질문"))
        self.assertIsNone(await select_tool_by_llm(FakeBoundLLM([]), "질문"))
        self.assertIsNone(await select_tool_by_llm(SimpleNamespace(), "질문"))

    async def test_llm_choice_is_not_overridden_by_pdf_keyword(self):
        # 예전에는 질문에 "pdf"가 있으면 LLM 선택을 무시하고 CreatePdf로 덮어썼다.
        pipeline = AgenticFakePipeline()
        pipeline.llm = FakeBoundLLM(
            [{"name": "SearchLaw", "args": {"query": "PDF 형식 의무", "top_k": 5}}]
        )
        graph = LangGraphRAG(pipeline)
        state = await graph.graph.ainvoke(
            {
                "question": "AI 기본법에 PDF 형식 제출 의무가 있나요?",
                "history": [],
                "retrieval_retries": 0,
                "answer_retries": 0,
            }
        )
        self.assertEqual(state["tool_name"], "SearchLaw")

    async def test_follow_up_routing_sees_original_request(self):
        pipeline = AgenticFakePipeline()
        llm = FakeBoundLLM([])
        pipeline.llm = llm
        with TemporaryDirectory() as directory, patch(
            "documents.pdf_report.REPORT_DIR", Path(directory)
        ):
            result = await LangGraphRAG(pipeline).answer(
                "이거 PDF로 저장해줘",
                history=[
                    {"question": "제33조 설명", "answer": "확인 절차 [S1]", "source_articles": ["제33조"]}
                ],
            )
        # LLM이 도구를 고르지 않으면 규칙 폴백으로 PDF가 만들어진다.
        self.assertEqual(result.method, "ToolCalling(CreatePdf)")
        routed = llm.inputs[0][1][1]
        self.assertIn("현재 요청: 이거 PDF로 저장해줘", routed)


if __name__ == "__main__":
    unittest.main()
