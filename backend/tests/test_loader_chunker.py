import unittest
from pathlib import Path

from rag.chunker import AdaptiveLawChunker
from rag.loader import LawXMLLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
XML_PATH = PROJECT_ROOT / "data" / "ai_basic_law" / "ai_basic_law.xml"


class LoaderChunkerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loader = LawXMLLoader(XML_PATH)
        cls.root = loader.load()
        cls.metadata = loader.metadata(cls.root)
        cls.chunks = AdaptiveLawChunker().chunk(cls.root, cls.metadata)

    def test_loads_expected_law(self):
        self.assertEqual(self.root.tag, "법령")
        self.assertIn("인공지능 발전", self.metadata.law_name)
        self.assertEqual(self.metadata.enforce_date, "20260721")

    def test_final_chunk_counts(self):
        summary = AdaptiveLawChunker.summary(self.chunks)
        self.assertEqual(summary["total"], 118)
        self.assertEqual(summary["searchable"], 111)
        self.assertEqual(summary["roles"]["parent"], 7)
        self.assertEqual(summary["roles"]["anchor"], 1)

    def test_high_impact_definition_anchor_exists(self):
        anchors = [
            chunk
            for chunk in self.chunks
            if chunk.get("article") == "제2조"
            and chunk.get("item_no") == "4"
            and chunk.get("chunk_role") == "anchor"
        ]
        self.assertEqual(len(anchors), 1)
        self.assertIn("고영향 인공지능", anchors[0]["content"])

    def test_headings_are_metadata_not_search_chunks(self):
        heading_only = [
            chunk
            for chunk in self.chunks
            if chunk["content"].startswith("제1절 ")
            and chunk.get("source_type") == "article"
        ]
        self.assertEqual(heading_only, [])


if __name__ == "__main__":
    unittest.main()
