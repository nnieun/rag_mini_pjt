import argparse
import asyncio
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from common.ai_model import get_embedding_model
from common.qdrant import get_qdrant_client
from rag.chunker import AdaptiveLawChunker
from rag.loader import LawXMLLoader
from rag.vectorstore import QdrantLawStore


async def main() -> None:
    parser = argparse.ArgumentParser(description="AI 기본법 XML을 Qdrant에 저장합니다.")
    parser.add_argument(
        "--xml",
        type=Path,
        default=Path("data/ai_basic_law/ai_basic_law.xml"),
    )
    parser.add_argument(
        "--collection",
        default="ai_basic_law_adaptive_anchor_v1",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="기존 컬렉션을 삭제하고 다시 생성합니다.",
    )
    args = parser.parse_args()

    root = LawXMLLoader(args.xml).load()
    chunks = AdaptiveLawChunker().chunk(root)
    store = QdrantLawStore(
        get_qdrant_client(),
        args.collection,
        get_embedding_model(),
    )
    count = await store.index(chunks, recreate=args.recreate)
    searchable = sum(chunk["search_enabled"] for chunk in chunks)
    print(f"저장 완료: {args.collection}")
    print(f"전체 {count}개 / 검색 가능 {searchable}개 / 부모 {count - searchable}개")


if __name__ == "__main__":
    asyncio.run(main())
