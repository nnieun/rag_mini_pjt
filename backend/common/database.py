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


def create_checkpoint_pool(
    connection_string: str = DATABASE_URL,
) -> AsyncConnectionPool:
    """LangGraph AsyncPostgresSaver용 풀. 체크포인터는 autocommit·dict_row 연결을 요구한다."""
    from psycopg.rows import dict_row

    return AsyncConnectionPool(
        conninfo=connection_string,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
