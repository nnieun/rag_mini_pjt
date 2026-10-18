# API 실행 가이드

## 실행

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Swagger UI는 `http://127.0.0.1:8000/docs`에서 확인한다.

## 질문 API

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"제33조 내용을 알려줘","refresh":false,"history":[]}'
```

후속 질문은 이전 질문·답변·출처를 구조화해서 전달한다.

```json
{
  "question": "그게 다야?",
  "thread_id": "conversation-123",
  "history": [
    {
      "question": "고영향 인공지능이란?",
      "answer": "이전 답변 [S1]",
      "source_articles": ["제2조"]
    }
  ]
}
```

LangGraph의 `resolve_follow_up` 노드가 이를 이전 대화 없이도 검색 가능한 질문으로 재작성하며, 실제 사용한 질의는 응답의 `resolved_question`에서 확인할 수 있다.

이전 답변이 있는 상태에서 `"방금 답변을 PDF로 만들어줘"`라고 요청하면 LLM이 `CreatePdf` 도구를 선택한다. 서버는 검증된 이전 답변과 조문 출처로 보고서를 생성하고 `/reports/{파일명}.pdf` 다운로드 주소를 반환한다.

응답에는 `answer`, `sources`, `status`, `missing_fields`, `request_id`, 처리 시간과 검색 메타데이터가 포함된다. `status`는 현재 `answered` 또는 `insufficient_evidence`를 반환한다.

요청은 LangGraph의 `analyze_and_select_tool → execute_tool → rewrite_query(선택) → generate → validate → prepare_retry(선택)` 흐름으로 처리된다. LLM Tool Calling을 지원하지 않는 호환 엔드포인트에서는 조문 번호와 질문 유형에 따라 같은 도구를 결정적으로 선택한다.

## 문서 추출 API

```bash
curl -X POST http://127.0.0.1:8000/documents/extract \
  -F 'file=@sample.pdf'
```

지원 형식은 TXT, XML, 텍스트 PDF, PNG, JPEG이며 기본 최대 크기는 10MB다. PNG/JPEG OCR은 시스템의 Tesseract를 사용한다. 한국어 OCR을 사용하려면 Tesseract와 한국어 언어 데이터를 설치해야 한다. 현재 스캔 PDF의 페이지 이미지 변환은 지원하지 않으며 명시적인 422 오류를 반환한다.

문서를 바로 요약하려면 다음 API를 사용한다.

```bash
curl -X POST http://127.0.0.1:8000/documents/summarize \
  -F 'file=@sample.pdf'
```

응답에는 추출 원문, 요약, 추출 방식과 모델 토큰 사용량이 포함된다.

## 설정

```env
RAG_LLM_TOOL_ROUTING_ENABLED=true
RAG_LLM_ANALYSIS_ENABLED=true
RAG_GRAPH_TIMEOUT_SECONDS=120
DOCUMENT_MAX_BYTES=10485760
```

## 테스트

```bash
cd backend
uv run python -m unittest discover -s tests -v
```

외부 LLM, Qdrant, PostgreSQL을 사용하는 평가 실행 방법은 `backend/eval/EVALUATION_GUIDE.md`를 참고한다.
