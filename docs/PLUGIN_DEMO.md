# MCP 서버와 Claude Code 플러그인 데모

이 문서는 `ai-basic-act` MCP 서버와 플러그인을 처음부터 확인하는 순서와 데모 시나리오 5개를 정리한다. 서버 설명은 [backend/mcp_server/README.md](../backend/mcp_server/README.md), 플러그인 설치는 [plugin/ai-basic-act/README.md](../plugin/ai-basic-act/README.md)에 있다.

## 구성

```text
Claude Code ──(plugin: skills, /law, /compliance)
     │
     └─ MCP (Streamable HTTP) ──> FastAPI /mcp ──> rag.tools.execute_tool ──> Qdrant Hybrid 검색
                                        │                                  └─> LangGraph 에이전트(ask_law)
Claude Desktop / Inspector ─ MCP (stdio) ──> python -m mcp_server ─┘
                                        │
                                        └─> PostgreSQL request_runs / tool_calls (channel = 'mcp')
```

## 1. 서버 확인

```bash
cd backend
uv run uvicorn app.main:app --port 8000
uv run python scripts/mcp_demo.py --url http://localhost:8000/mcp > ../docs/PLUGIN_DEMO.result.md
```

`scripts/mcp_demo.py`는 아래 시나리오의 MCP 호출을 그대로 실행하고 결과를 Markdown으로 출력한다. 실제 Qdrant·LLM 환경에서 실행한 결과를 `PLUGIN_DEMO.result.md`로 남긴다.

## 2. 시나리오

| # | 사용자 입력 (Claude Code) | Claude가 쓰는 MCP 호출 | 확인할 점 |
|---|---|---|---|
| 1 | `/law 제33조` | `get_article(33)` | 조·항별 원문이 그대로 나오고 조문 번호가 정확한지 |
| 2 | `/law 생성형 AI 결과물에 표시 의무가 있나?` | `search_law` → `get_article` | 검색된 조문을 원문으로 다시 확인한 뒤 인용하는지 |
| 3 | `고영향 인공지능 사업자는 어떤 의무가 있어?` (스킬 `law-citation` 자동 사용) | `ask_law` → `get_article` | 답변의 sources와 인용 조문이 일치하는지 |
| 4 | `/law` (빈 입력) | 리소스 `law://ai-basic-act/toc` | 목차를 보여 주고 무엇을 찾을지 묻는지 |
| 5 | `/compliance 이력서를 읽고 지원자 점수를 매기는 채용 보조 AI` | 프롬프트 `compliance_check` → `search_law` × n → `get_article` | 의무·해당 여부·근거 조문·할 일 표와 "법률 자문 아님" 문구 |

시나리오 2, 3에서 "법령에서 확인되지 않음"이 나와야 하는 질문(예: 벌금 액수처럼 원문에 없는 내용)을 하나 섞어 추측하지 않는지도 본다.

## 3. 저장소 안에서 확인한 것

실제 Qdrant·LLM 없이 가짜 파이프라인으로 다음을 자동 테스트와 수동 실행으로 확인했다.

- `scripts/mcp_demo.py`를 가짜 파이프라인의 uvicorn 서버(`/mcp`)에 실행: 5개 호출 모두 성공
- `claude plugin validate`: 플러그인과 마켓플레이스 매니페스트 통과
- 로컬 클론을 마켓플레이스로 추가하고 `ai-basic-act@rag-mini-pjt` 설치, `claude mcp list`에서 `plugin:ai-basic-act:ai-basic-act … Connected`
- 실제 PostgreSQL 16에서 `004_tool_calls_channel.sql`을 기존 003 스키마 위에 적용하고 MCP 호출이 `channel='mcp'`, 64자 `arguments_hash`로 저장되는지

## 4. 로컬에서 남은 확인

실제 키와 인덱스가 필요해 저장소 CI에서는 하지 못한 항목이다.

- [ ] 실제 환경에서 `scripts/mcp_demo.py` 실행 결과를 `docs/PLUGIN_DEMO.result.md`로 저장
- [ ] MCP Inspector 스크린샷: Tools 목록, `get_article(33)` 결과, `search_law` 검증 오류 (`docs/assets/mcp-inspector-*.png`)
- [ ] Claude Code에서 시나리오 1~5 실행, 시나리오 5 화면 녹화 GIF (`docs/assets/plugin-demo.gif`)
- [ ] Claude Desktop에 stdio 서버 등록 후 시나리오 3 확인
- [ ] 외부 MCP 클라이언트: `config/mcp_servers.example.json`을 `mcp_servers.json`으로 복사하고 "생성된 보고서 목록 보여줘" 질문이 `filesystem_list_directory`로 가는지

스크린샷과 GIF를 넣은 뒤 아래 자리에 링크한다.

<!-- ![MCP Inspector](assets/mcp-inspector-tools.png) -->
<!-- ![플러그인 데모](assets/plugin-demo.gif) -->
