from types import SimpleNamespace
import unittest

from pydantic import ValidationError

from app.main import AskRequest, AskResponse, SourceResponse, create_app


class FakePipeline:
    def __init__(self):
        self.retriever = SimpleNamespace(
            collection_name="test-collection",
            chunks=[{}, {}],
            chunks_by_key={"a": {}, "b": {}, "c": {}},
        )

    def close(self):
        pass


class ApiTest(unittest.TestCase):
    def test_required_routes_exist(self):
        app = create_app(FakePipeline)
        routes = {
            (route.path, method)
            for route in app.routes
            for method in (route.methods or set())
        }
        self.assertIn(("/health", "GET"), routes)
        self.assertIn(("/ask", "POST"), routes)
        self.assertIn(("/docs", "GET"), routes)

    def test_openapi_ask_schema(self):
        schema = create_app(FakePipeline).openapi()
        self.assertIn("/ask", schema["paths"])
        response_schema = schema["components"]["schemas"]["AskResponse"]
        self.assertIn("answer", response_schema["properties"])
        self.assertIn("sources", response_schema["properties"])
        self.assertIn("retrieved_articles", response_schema["properties"])

    def test_question_validation(self):
        with self.assertRaises(ValidationError):
            AskRequest(question=" ")
        request = AskRequest(question="고영향 인공지능이란?")
        self.assertEqual(request.question, "고영향 인공지능이란?")

    def test_response_serialization(self):
        response = AskResponse(
            answer="테스트 답변 [S1]",
            sources=[
                SourceResponse(
                    source_id="S1",
                    article="제2조",
                    item="4호",
                    title="정의",
                    content="테스트 근거",
                )
            ],
            method="Hybrid(Dense+BM25+RRF)",
            retrieved_articles=["제2조"],
            elapsed_ms=10.0,
        )
        self.assertEqual(response.sources[0].article, "제2조")


if __name__ == "__main__":
    unittest.main()
