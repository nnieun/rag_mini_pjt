import unittest

from rag.graph import classify_question, grade_answer, grade_documents, rewrite_query
from rag.schemas import RequestAnalysis


class GraphTest(unittest.TestCase):
    def test_question_classification(self):
        self.assertEqual(
            classify_question({"question": "고영향 인공지능이란?"})[
                "question_type"
            ],
            "definition",
        )
        self.assertEqual(
            classify_question({"question": "의무 관련 조문을 정리해줘"})[
                "question_type"
            ],
            "obligation",
        )
        self.assertEqual(
            classify_question({"question": "표시 의무를 알려줘"})[
                "question_type"
            ],
            "general",
        )

    def test_definition_query_is_rewritten_conservatively(self):
        state = classify_question({"question": "고영향 인공지능이란?"})
        self.assertEqual(state["rewritten_question"], "고영향 인공지능이란? 정의")
        self.assertEqual(
            rewrite_query(
                "표시 의무를 알려 주세요",
                RequestAnalysis(intent="general"),
            ),
            "표시 의무를",
        )

    def test_document_and_answer_grading(self):
        documents = [{"article": "제2조", "content": "고영향 인공지능의 정의"}]
        self.assertGreater(grade_documents("고영향 인공지능 정의", documents), 0)
        self.assertEqual(grade_documents("전혀 다른 질문", documents), 0)
        self.assertTrue(grade_answer("제공된 AI 기본법 근거에서는 확인할 수 없습니다", 0))
        self.assertTrue(grade_answer("제2조에 따른 내용입니다. [S1]", 1))
        self.assertFalse(grade_answer("근거 없는 답변", 1))

if __name__ == "__main__":
    unittest.main()
