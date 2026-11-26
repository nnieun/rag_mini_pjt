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
from rag.references import attach_references, reference_rows
from rag.vectorstore import QdrantLawStore

REFERENCES_SQL = BACKEND_ROOT / "docker" / "postgres-init" / "006_article_references.sql"


async def save_references(chunks: list[dict], law_id: str, law_version: str) -> int:
    """article_references 테이블을 이번 법령 버전 기준으로 다시 채운다."""
    from common.database import create_database_pool

    rows = reference_rows(chunks)
    pool = create_database_pool()
    await pool.open(wait=True, timeout=5.0)
    try:
        async with pool.connection() as connection:
            sql = REFERENCES_SQL.read_text(encoding="utf-8").replace("BEGIN;", "").replace("COMMIT;", "")
            await connection.execute(sql)
            await connection.execute(
                "DELETE FROM article_references WHERE law_id = %s AND law_version = %s",
                (law_id, law_version),
            )
            async with connection.cursor() as cursor:
                await cursor.executemany(
                    "INSERT INTO article_references "
                    "(law_id, law_version, source_article, target_article, target_paragraph, chunk_key) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    [(law_id, law_version, *row) for row in rows],
                )
            await connection.commit()
    finally:
        await pool.close()
    return len(rows)


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
    parser.add_argument(
        "--skip-references-db",
        action="store_true",
        help="PostgreSQL article_references 테이블을 채우지 않습니다.",
    )
    args = parser.parse_args()

    loader = LawXMLLoader(args.xml)
    root = loader.load()
    metadata = loader.metadata(root)
    chunks = attach_references(AdaptiveLawChunker().chunk(root, metadata))
    store = QdrantLawStore(
        get_qdrant_client(),
        args.collection,
        get_embedding_model(),
    )
    count = await store.index(chunks, recreate=args.recreate)
    searchable = sum(chunk["search_enabled"] for chunk in chunks)
    print(f"저장 완료: {args.collection}")
    print(f"전체 {count}개 / 검색 가능 {searchable}개 / 부모 {count - searchable}개")
    if not args.skip_references_db:
        try:
            saved = await save_references(chunks, metadata.law_id, chunks[0]["law_version"])
            print(f"조문 인용 관계 {saved}건을 article_references에 저장")
        except Exception as error:
            print(f"article_references 저장 건너뜀(PostgreSQL 연결 실패): {error}")


if __name__ == "__main__":
    asyncio.run(main())
