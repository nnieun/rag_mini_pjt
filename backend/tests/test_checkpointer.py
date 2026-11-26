from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver

from rag.graph import LangGraphRAG, checkpoint_serde
from tests.test_agentic_features import AgenticFakePipeline


class CheckpointerTest(unittest.IsolatedAsyncioTestCase):
    def make_rag(self):
        return LangGraphRAG(AgenticFakePipeline(), checkpointer=InMemorySaver(serde=checkpoint_serde()))

    async def test_same_thread_remembers_previous_turn_without_history(self):
        rag = self.make_rag()
        await rag.answer("고영향 인공지능이란?", thread_id="t1")
        follow_up = await rag.answer("그게 다야?", thread_id="t1")
        # 클라이언트가 history를 보내지 않아도 이전 질문이 문맥으로 쓰인다.
        self.assertIn("고영향 인공지능이란", follow_up.resolved_question)

    async def test_threads_are_isolated(self):
        rag = self.make_rag()
        await rag.answer("고영향 인공지능이란?", thread_id="t1")
        other = await rag.answer("그게 다야?", thread_id="t2")
        self.assertEqual(other.resolved_question, "그게 다야?")

    async def test_client_history_takes_precedence(self):
        rag = self.make_rag()
        await rag.answer("고영향 인공지능이란?", thread_id="t1")
        result = await rag.answer(
            "그게 다야?",
            thread_id="t1",
            history=[{"question": "제33조 확인 절차는?", "answer": "답 [S1]", "source_articles": []}],
        )
        self.assertIn("제33조 확인 절차는", result.resolved_question)

    async def test_turns_accumulate_and_transient_fields_reset(self):
        rag = self.make_rag()
        config = {"configurable": {"thread_id": "t1"}}
        with TemporaryDirectory() as directory, patch(
            "documents.pdf_report.REPORT_DIR", Path(directory)
        ):
            await rag.answer("제33조 내용 알려줘", thread_id="t1")
            pdf = await rag.answer("방금 답변 PDF로 만들어줘", thread_id="t1")
            self.assertEqual(pdf.method, "ToolCalling(CreatePdf)")
            # 이전 턴의 artifact_url이 남아 있으면 다음 질문도 PDF 응답으로 끝난다.
            after = await rag.answer("제33조 내용 알려줘", thread_id="t1")
        self.assertNotEqual(after.method, "ToolCalling(CreatePdf)")
        state = (await rag.memory_graph.aget_state(config)).values
        # PDF 턴은 대화 기록에 남기지 않는다.
        self.assertEqual(len(state["turns"]), 2)
        self.assertEqual(state["turns"][0]["source_articles"], ["제33조"])

    async def test_without_thread_id_nothing_is_checkpointed(self):
        saver = InMemorySaver(serde=checkpoint_serde())
        rag = LangGraphRAG(AgenticFakePipeline(), checkpointer=saver)
        await rag.answer("고영향 인공지능이란?")
        self.assertEqual(list(saver.list(None)), [])


if __name__ == "__main__":
    unittest.main()
