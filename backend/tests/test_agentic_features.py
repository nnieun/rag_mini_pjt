from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from documents.processor import extract_document
from rag.graph import LangGraphRAG
from rag.models import AnswerResult, Source
from rag.tools import execute_tool
from rag.validators import validate_answer


class AgenticFakePipeline:
    def __init__(self):
        self.llm = SimpleNamespace()
        self.retriever = SimpleNamespace(
            chunks_by_key={
                "a": {
                    "chunk_id": "a",
                    "article": "제33조",
                    "title": "고영향 인공지능의 확인",
                    "content": "고영향 인공지능 해당 여부를 확인한다.",
                }
            }
        )

    async def retrieve(self, question, *, k=None, use_reranking=False):
        return list(self.retriever.chunks_by_key.values())

    async def answer(self, question, **kwargs):
        return AnswerResult(
            answer="제33조에 따라 확인합니다. [S1]",
            sources=[Source("S1", "제33조", "", "", "", "확인", "근거")],
            method="fake",
            retrieved_articles=["제33조"],
        )


class AgenticFeatureTest(unittest.IsolatedAsyncioTestCase):
    async def test_exact_article_tool_and_compiled_graph(self):
        pipeline = AgenticFakePipeline()
        results = await execute_tool(pipeline, "GetArticle", {"article_number": 33})
        self.assertEqual(results[0]["article"], "제33조")

        result = await LangGraphRAG(pipeline).answer("제33조 내용을 알려줘")
        self.assertIn("[S1]", result.answer)

    async def test_follow_up_is_resolved_to_standalone_query(self):
        pipeline = AgenticFakePipeline()
        result = await LangGraphRAG(pipeline).answer(
            "그게 다야?",
            history=[
                {
                    "question": "고영향 인공지능이란?",
                    "answer": "고영향 인공지능의 정의입니다. [S1]",
                    "source_articles": ["제2조"],
                }
            ],
            thread_id="test-thread",
        )
        self.assertIn("고영향 인공지능이란", result.resolved_question)
        self.assertIn("누락된 관련 조문", result.resolved_question)

    async def test_pdf_tool_call_creates_downloadable_report(self):
        pipeline = AgenticFakePipeline()
        with TemporaryDirectory() as directory, patch(
            "documents.pdf_report.REPORT_DIR", Path(directory)
        ):
            result = await LangGraphRAG(pipeline).answer(
                "방금 답변을 PDF로 만들어줘",
                history=[
                    {
                        "question": "제33조를 설명해줘",
                        "answer": "제33조에 따른 확인 절차입니다. [S1]",
                        "source_articles": ["제33조"],
                    }
                ],
            )
            self.assertEqual(result.method, "ToolCalling(CreatePdf)")
            self.assertIn("/reports/law-report-", result.answer)
            self.assertEqual(len(list(Path(directory).glob("*.pdf"))), 1)

    def test_text_document_and_answer_validation(self):
        document = extract_document(
            "law.txt", "text/plain", "제33조 확인 의무".encode("utf-8")
        )
        self.assertEqual(document.extraction_method, "text")
        self.assertIn("제33조", document.text)

        valid = validate_answer(
            AnswerResult(
                "근거 답변 [S1]",
                [Source("S1", "제33조", "", "", "", "확인", "근거")],
                "fake",
                ["제33조"],
            )
        )
        self.assertTrue(valid.valid)


if __name__ == "__main__":
    unittest.main()
