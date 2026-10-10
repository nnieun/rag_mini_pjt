import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from common.database import create_database_pool


async def main() -> None:
    pool = create_database_pool()
    await pool.open()
    try:
        async with pool.connection() as connection:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT current_database(), current_user")
                database, user = await cursor.fetchone()
                await cursor.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public'"
                )
                table_count = (await cursor.fetchone())[0]
        print(f"PostgreSQL 연결 성공: database={database}, user={user}")
        print(f"public 테이블 수: {table_count}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
