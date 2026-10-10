from psycopg_pool import AsyncConnectionPool

from common.config import DATABASE_URL


def create_database_pool(
    connection_string: str = DATABASE_URL,
) -> AsyncConnectionPool:
    """애플리케이션 lifespan에서 열고 닫을 PostgreSQL 연결 풀을 생성합니다."""
    return AsyncConnectionPool(
        conninfo=connection_string,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"autocommit": False},
    )
