import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime, timedelta

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from rag.models import AnswerResult, Source


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS answer_cache (
    cache_key char(64) PRIMARY KEY,
    normalized_question text NOT NULL,
    collection_name varchar(200) NOT NULL,
    pipeline_version varchar(100) NOT NULL,
    response_payload jsonb NOT NULL,
    hit_count bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_answer_cache_expires_at
    ON answer_cache (expires_at);
"""


def normalize_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKC", question).strip().lower()
    return re.sub(r"\s+", " ", normalized)


class PostgresAnswerCache:
    def __init__(
        self,
        pool: AsyncConnectionPool,
        *,
        collection_name: str,
        pipeline_version: str,
        ttl_days: int = 30,
    ):
        self.pool = pool
        self.collection_name = collection_name
        self.pipeline_version = pipeline_version
        self.ttl = timedelta(days=ttl_days)

    async def open(self) -> None:
        await self.pool.open(wait=True, timeout=5.0)
        async with self.pool.connection() as connection:
            await connection.execute(SCHEMA_SQL)
            await connection.commit()

    async def close(self) -> None:
        await self.pool.close()

    def key_for(self, question: str) -> tuple[str, str]:
        normalized = normalize_question(question)
        material = "\n".join(
            (normalized, self.collection_name, self.pipeline_version)
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest(), normalized

    async def get(self, question: str) -> AnswerResult | None:
        cache_key, _ = self.key_for(question)
        async with self.pool.connection() as connection:
            cursor = await connection.execute(
                """
                SELECT response_payload FROM answer_cache
                WHERE cache_key = %s AND expires_at > now()
                """,
                (cache_key,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            await connection.execute(
                """
                UPDATE answer_cache
                SET hit_count = hit_count + 1, updated_at = now()
                WHERE cache_key = %s
                """,
                (cache_key,),
            )
            await connection.commit()

        payload = row[0]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return AnswerResult(
            answer=payload["answer"],
            sources=[Source(**source) for source in payload["sources"]],
            method=payload["method"],
            retrieved_articles=payload["retrieved_articles"],
            cache_hit=True,
            processing_ms=float(payload.get("processing_ms", 0.0)),
            total_relevant=int(
                payload.get("total_relevant", len(payload["sources"]))
            ),
            displayed_count=int(
                payload.get("displayed_count", len(payload["sources"]))
            ),
            has_more=bool(payload.get("has_more", False)),
            model_usage=dict(payload.get("model_usage", {})),
            resolved_question=str(payload.get("resolved_question", "")),
        )

    async def put(self, question: str, result: AnswerResult) -> None:
        cache_key, normalized = self.key_for(question)
        expires_at = datetime.now(UTC) + self.ttl
        async with self.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO answer_cache (
                    cache_key, normalized_question, collection_name,
                    pipeline_version, response_payload, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (cache_key) DO UPDATE SET
                    response_payload = EXCLUDED.response_payload,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = now()
                """,
                (
                    cache_key,
                    normalized,
                    self.collection_name,
                    self.pipeline_version,
                    Jsonb(result.as_dict()),
                    expires_at,
                ),
            )
            await connection.commit()
