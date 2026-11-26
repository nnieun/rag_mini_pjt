# ai-basic-act (Claude Code 플러그인)

AI 기본법 RAG 백엔드의 MCP 서버를 Claude Code에 연결하고, 조문 인용과 준수 점검을 위한 스킬과 커맨드를 함께 설치한다.

| 구성 | 내용 |
|---|---|
| MCP 서버 `ai-basic-act` | `search_law`, `get_article`, `ask_law` 도구, `law://ai-basic-act/toc`·`law://ai-basic-act/articles/{n}` 리소스, `compliance_check` 프롬프트 |
| 스킬 `law-citation` | 조문을 원문 확인 후 조·항·호 형식으로 인용 |
| 스킬 `compliance-check` | 서비스 설명을 받아 의무·근거 조문·할 일을 표로 정리 |
| 커맨드 `/law` | 질문 또는 조문 번호로 근거 있는 답변 |
| 커맨드 `/compliance` | 서비스 설명으로 준수 점검 |

## 설치

1. 백엔드를 띄운다. MCP는 FastAPI 앱의 `/mcp`(Streamable HTTP)로 함께 열린다.

   ```bash
   cd backend
   uv run uvicorn app.main:app --port 8000
   ```

2. Claude Code에서 마켓플레이스를 추가하고 설치한다.

   ```text
   /plugin marketplace add nnieun/rag_mini_pjt
   /plugin install ai-basic-act@rag-mini-pjt
   ```

   로컬 클론에서 시험할 때는 `/plugin marketplace add ./`를 쓴다.

3. `/mcp`에서 `plugin:ai-basic-act:ai-basic-act`가 connected인지 확인한다.

## 설정

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `AI_BASIC_ACT_MCP_URL` | `http://localhost:8000/mcp` | 백엔드 MCP 주소 |
| `AI_BASIC_ACT_MCP_TOKEN` | 비어 있음 | 백엔드에 `RAG_MCP_TOKEN`을 설정했으면 같은 값 |

백엔드를 다른 호스트에서 열 때는 백엔드 쪽에 `RAG_MCP_ALLOWED_HOSTS`, `RAG_MCP_TOKEN`도 설정한다(`backend/.env.example` 참고).

## Claude Desktop에서 쓰기 (stdio)

플러그인 없이 MCP 서버만 붙일 때는 `claude_desktop_config.json`에 stdio 서버로 등록한다. 이 방식은 서버 프로세스가 직접 Qdrant와 인덱스를 연다.

```json
{
  "mcpServers": {
    "ai-basic-act": {
      "command": "uv",
      "args": ["--directory", "/절대/경로/rag_mini_pjt/backend", "run", "python", "-m", "mcp_server"]
    }
  }
}
```

## 예시

```text
/law 제33조
/law 생성형 AI 결과물에 표시 의무가 있나?
/compliance 이력서를 읽고 지원자에게 점수를 매기는 채용 보조 AI
```
