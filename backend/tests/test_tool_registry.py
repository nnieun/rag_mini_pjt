import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from rag.graph import select_tool_by_llm, select_tool_by_rule
from rag.schemas import RequestAnalysis
from rag.tools import REGISTRY, allowed_specs, execute_tool, load_allowed_tools
from tests.test_agentic_features import AgenticFakePipeline
from tests.test_tool_selection import FakeBoundLLM


class RegistryTest(unittest.TestCase):
    def test_registry_has_schema_and_description_for_every_tool(self):
        self.assertEqual(set(REGISTRY), {"SearchLaw", "GetArticle", "GetRelatedArticles", "CreatePdf"})
        for spec in REGISTRY.values():
            self.assertTrue(spec.description)
            self.assertIn("properties", spec.args_model.model_json_schema())

    def test_default_config_allows_all_registered_tools(self):
        self.assertEqual(load_allowed_tools(), frozenset(REGISTRY))

    def test_unknown_names_in_config_are_ignored(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "tools.json"
            path.write_text(json.dumps({"allowed": ["SearchLaw", "DropTable"]}))
            with self.assertLogs("rag.tools", level="WARNING"):
                self.assertEqual(load_allowed_tools(path), frozenset({"SearchLaw"}))

    def test_rule_never_picks_hidden_tool(self):
        name, _ = select_tool_by_rule(
            "제33조 PDF로 줘", "제33조 PDF로 줘", "제33조", RequestAnalysis(article_number=33),
            allowed=frozenset({"SearchLaw"}),
        )
        self.assertEqual(name, "SearchLaw")


class ExecuteToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_hidden_tool_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "허용되지 않은 도구"):
            await execute_tool(
                AgenticFakePipeline(), "GetArticle", {"article_number": 33},
                allowed=frozenset({"SearchLaw"}),
            )

    async def test_invalid_arguments_raise_validation_error(self):
        with self.assertRaises(ValidationError):
            await execute_tool(AgenticFakePipeline(), "GetArticle", {"article_number": 0})

    async def test_create_pdf_runs_through_registry(self):
        with TemporaryDirectory() as directory, patch(
            "documents.pdf_report.REPORT_DIR", Path(directory)
        ):
            url = await execute_tool(
                AgenticFakePipeline(), "CreatePdf", {},
                history=[{"question": "q", "answer": "a", "source_articles": ["제2조"]}],
            )
        self.assertTrue(url.startswith("/reports/"))

    async def test_create_pdf_without_history_fails(self):
        with self.assertRaisesRegex(ValueError, "이전 답변"):
            await execute_tool(AgenticFakePipeline(), "CreatePdf", {})

    async def test_llm_sees_only_allowed_tools(self):
        bound = []

        class Recorder(FakeBoundLLM):
            def bind_tools(self, tools):
                bound.extend(tools)
                return self

        with patch("rag.graph.allowed_specs", lambda: allowed_specs(frozenset({"SearchLaw"}))):
            await select_tool_by_llm(Recorder([]), "질문")
        self.assertEqual([model.__name__ for model in bound], ["SearchLaw"])


if __name__ == "__main__":
    unittest.main()
