# AI 기본법 MCP 서버

`backend/mcp_server`는 RAG 백엔드의 도구를 [Model Context Protocol](https://modelcontextprotocol.io) 서버로 연다. 도구 실행은 HTTP API와 같은 `rag.tools.execute_tool`을 거치므로 인자 검증, `config/tools.json` 허용 목록, 호출 기록이 그대로 적용된다.

## 제공 기능

| 종류 | 이름 | 설명 |
|---|---|---|
| 도구 | `search_law(query, top_k=5)` | Hybrid 검색(Dense + BM25 + RRF)으로 관련 조문. `query` 2~1000자, `top_k` 1~20 |
| 도구 | `get_article(article_number)` | 특정 조문을 조·항·호 단위 원문으로. 없는 조문이면 오류 |
| 도구 | `ask_law(question)` | LangGraph 에이전트 답변과 출처. `RAG_MCP_ASK_ENABLED=false`로 숨김 |
| 리소스 | `law://ai-basic-act/toc` | 조 번호와 제목 목차 |
| 리소스 | `law://ai-basic-act/articles/{n}` | 제n조 원문 텍스트 |
| 프롬프트 | `compliance_check(service_description)` | 서비스 설명을 받아 의무 점검표를 만드는 지시문 |

`search_law`, `get_article`은 `config/tools.json`의 `SearchLaw`, `GetArticle`이 허용돼 있을 때만 등록된다. `CreatePdf`는 서버 파일을 만드는 도구라 MCP로 열지 않는다.

## 실행

### stdio (Claude Desktop, MCP Inspector)

```bash
cd backend
uv run python -m mcp_server
```

서버 프로세스가 직접 Qdrant와 BM25 인덱스를 연다. 파이프라인은 첫 도구 호출 때 불러오므로 도구 목록 조회는 바로 응답한다.

### Streamable HTTP (FastAPI `/mcp`)

```bash
cd backend
uv run uvicorn app.main:app --port 8000
# MCP 엔드포인트: http://localhost:8000/mcp
```

FastAPI 앱이 이미 불러온 파이프라인과 에이전트를 같이 쓴다. stateless, JSON 응답 모드라 프록시 뒤에서도 세션 고정이 필요 없다.

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `RAG_MCP_HTTP_ENABLED` | `true` | `/mcp` 라우트 등록 |
| `RAG_MCP_TOKEN` | 비어 있음 | 설정하면 `Authorization: Bearer <token>` 필요 |
| `RAG_MCP_ALLOWED_HOSTS` | `127.0.0.1:*,localhost:*,[::1]:*` | DNS rebinding 방지용 Host 허용 목록. `*`면 검사 안 함 |
| `RAG_MCP_ALLOWED_ORIGINS` | localhost 출처 | 허용 Origin |
| `RAG_MCP_ASK_ENABLED` | `true` | `ask_law` 노출 |

외부에 열 때는 `RAG_MCP_TOKEN`과 `RAG_MCP_ALLOWED_HOSTS`를 반드시 설정한다.

## 호출 기록

MCP 도구 호출마다 `RequestTrace`가 하나 만들어지고(`endpoint = mcp:<Tool>`), PostgreSQL이 연결돼 있으면 `request_runs`/`tool_calls`에 저장된다. `tool_calls.channel`은 `mcp`, `tool_calls.arguments_hash`는 인자 JSON의 SHA-256이다(질문 원문은 저장하지 않음). HTTP는 FastAPI의 추적 저장소를, stdio는 서버 lifespan에서 연 저장소를 쓴다.

```sql
SELECT r.endpoint, t.tool_name, t.status, t.elapsed_ms, r.created_at
FROM tool_calls t JOIN request_runs r ON r.id = t.request_run_id
WHERE t.channel = 'mcp'
ORDER BY r.created_at DESC LIMIT 20;
```

## MCP Inspector로 확인

```bash
npx @modelcontextprotocol/inspector uv --directory backend run python -m mcp_server
```

Inspector에서 Tools → `get_article`에 `33`을 넣어 원문이 오는지, `search_law`에 `query: "x"`를 넣어 검증 오류(`isError`)가 오는지 확인한다.

## 테스트

```bash
cd backend
uv run python -m unittest tests.test_mcp_server tests.test_mcp_http tests.test_mcp_stdio tests.test_plugin_manifest -v
```

- `test_mcp_server`: 메모리 세션으로 도구 목록, 정상 호출, 스키마 오류, 미허용 도구, 리소스, 프롬프트, 추적
- `test_mcp_http`: `/mcp` Streamable HTTP, 토큰, Host 검사, 추적 저장
- `test_mcp_stdio`: 실제 서브프로세스 stdio 서버
- `test_plugin_manifest`: 플러그인 스킬에 적힌 도구 이름이 서버에 있는지

## 데모

`scripts/mcp_demo.py`가 플러그인 스킬이 쓰는 5가지 호출을 실행해 Markdown으로 출력한다. [docs/PLUGIN_DEMO.md](../../docs/PLUGIN_DEMO.md) 참고.
