# Qdrant + PostgreSQL

이 Compose 프로젝트는 법령 벡터 검색용 Qdrant와 서비스 데이터 저장용 PostgreSQL을 실행한다.

## 실행

```bash
cd backend/docker
docker compose up -d
docker compose ps
```

Qdrant가 이미 실행 중이면 PostgreSQL만 추가할 수 있다.

```bash
docker compose up -d postgres
```

이 명령은 기존 Qdrant 컨테이너와 `qdrant_storage` 볼륨을 삭제하지 않는다.

## 접속 정보

| 서비스 | 주소 |
|---|---|
| Qdrant API | `http://localhost:6333` |
| Qdrant Dashboard | `http://localhost:6333/dashboard` |
| PostgreSQL | `localhost:5432` |
| Database | `ai_basic_law` |
| User | `aiuser` |

기본 비밀번호는 로컬 개발 전용 `local_dev_password`다. 실제 배포에서는 Compose 실행 전 `POSTGRES_PASSWORD`와 `DATABASE_URL`을 반드시 변경한다.

## PostgreSQL 확인

```bash
cd backend
uv sync
uv run python scripts/check_postgres.py
```

또는 컨테이너에서 직접 확인한다.

```bash
docker compose exec postgres psql -U aiuser -d ai_basic_law -c '\dt'
```

## 초기 SQL 주의사항

`postgres-init/001_schema.sql`은 `postgres_storage` 볼륨이 비어 있는 최초 실행 때만 자동 실행된다. SQL을 수정해도 이미 생성된 DB에는 자동으로 다시 적용되지 않는다. 운영 단계에서는 Alembic 같은 마이그레이션 도구를 사용해야 한다.

PostgreSQL 데이터만 초기화해야 할 때는 Qdrant 볼륨을 건드리지 말고 PostgreSQL 볼륨만 명시적으로 삭제한다. 데이터가 모두 삭제되는 작업이므로 백업 후 실행한다.

```bash
docker compose down
docker volume rm docker-qdrant_postgres_storage
docker compose up -d postgres
```

`docker compose down -v`는 Qdrant 데이터 볼륨까지 함께 삭제하므로 사용하지 않는다.
