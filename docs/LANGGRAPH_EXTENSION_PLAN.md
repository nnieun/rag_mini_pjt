# LangGraph 확장 계획

현재 프로젝트는 RAG 파이프라인, Qdrant 검색, reranker, retry, PostgreSQL 캐시, 평가 코드를 갖추고 있다. 따라서 LangGraph는 기존 로직을 다시 구현하기보다 검색·검증·재질의 과정을 상태 기반 그래프로 연결하는 계층으로 사용하는 것이 적합하다.

참고 저장소: [nnieun/LangGraph](https://github.com/nnieun/LangGraph)

## 1. Adaptive RAG 그래프

```text
질문 입력
  ↓
질문 유형 분류
  ├─ 법령 정의 질문 → 일반 검색
  ├─ 특정 조문 질문 → 조문 중심 검색
  ├─ 비교/복합 질문 → 다중 검색
  └─ 불명확한 질문 → 질의 재작성
        ↓
Qdrant 검색
        ↓
Reranker
        ↓
문서 관련성 평가
  ├─ 충분함 → 답변 생성
  └─ 부족함 → 검색 조건 변경 또는 질의 재작성
        ↓
답변 근거성 평가
  ├─ 통과 → 응답
  └─ 실패 → 재생성 또는 보류
```

추천 노드:

```text
classify_question
retrieve
rerank
grade_documents
rewrite_query
generate_answer
grade_answer
fallback
```

현재 코드에서는 다음 모듈을 노드 내부에서 재사용한다.

- `rag/retriever.py`
- `rag/reranker.py`
- `rag/retry.py`
- `rag/pipeline.py`
- `common/answer_cache.py`

## 2. 법령 전용 라우터

| 질문 유형 | 검색 전략 |
|---|---|
| 용어 정의 | 정의 조항, 제2조 우선 검색 |
| 특정 조문 | 조문 번호 및 제목 가중치 |
| 적용 대상 | 관련 조문 및 하위 규정 검색 |
| 예외·조건 | 조건 표현과 조항 주변 문맥 검색 |
| 비교 질문 | 여러 조문 병렬 검색 |
| 최신성 질문 | 법령 버전과 시행일 필터 |

질문 유형에 따라 검색 전략을 다르게 적용하면 이 프로젝트의 차별화 포인트가 될 수 있다.

## 3. 병렬 검색 및 결과 통합

```text
질문 분해
  ├─ 개념 검색
  ├─ 관련 조문 검색
  ├─ 예외 조건 검색
  └─ 시행일·법령 버전 검색
        ↓
결과 병합
        ↓
중복 제거 및 rerank
        ↓
답변 생성
```

LangGraph의 서브그래프를 사용해 `definition_search`, `article_search`, `exception_search`를 독립적인 검색 흐름으로 분리할 수 있다.

## 4. 답변 검증 및 자동 재시도

```text
generate_answer
  ↓
check_citation
  ↓
check_groundedness
  ↓
check_question_relevance
```

- 근거가 부족하면 검색 결과를 다시 확장한다.
- 질문과 무관하면 질의를 재작성한다.
- 법령 조항이 틀리면 답변을 재생성한다.
- 최대 재시도 횟수를 넘으면 근거 부족으로 응답한다.

## 5. PostgreSQL 기반 대화 메모리

PostgreSQL checkpointer를 연결하면 사용자별 대화 thread 유지, 후속 질문 처리, 중단된 실행 재개, 실패 노드 재실행, 실행 과정 replay/debug를 구현할 수 있다.

```python
class RAGState(TypedDict):
    question: str
    rewritten_question: str | None
    question_type: str | None
    documents: list
    citations: list
    answer: str | None
    retry_count: int
    confidence: float | None
```

LangGraph에서는 `thread_id`를 기준으로 그래프 상태를 저장하고 재사용한다.

## 6. Human-in-the-loop 검토

다음 상황에서 사람 검토를 넣을 수 있다.

- 근거 문서가 부족한 경우
- 검색 결과 간 법령 버전이 충돌하는 경우
- 답변 confidence가 낮은 경우
- 법률 적용 가능성이나 판단을 요구하는 경우

```text
답변 생성
  ↓
신뢰도 검사
  ├─ 높음 → 자동 응답
  ├─ 중간 → 주의 문구와 함께 응답
  └─ 낮음 → 사용자 확인 또는 관리자 검토
```

LangGraph의 `interrupt()`를 사용하면 실행을 중단한 뒤 외부 입력을 받아 그래프를 재개할 수 있다.

## 추천 개발 순서

1. `rag/pipeline.py`를 LangGraph의 단일 그래프로 감싼다.
2. `question_type` 기반 검색 라우터를 추가한다.
3. 문서 관련성 평가와 query rewrite를 추가한다.
4. 답변 근거성 및 citation 검증을 추가한다.
5. PostgreSQL checkpointer를 연결한다.
6. 병렬 검색과 human-in-the-loop를 추가한다.
7. 기존 `eval/` 결과와 LangGraph 적용 전후 성능을 비교한다.

## 1차 구현 권장 구조

```text
START
  ↓
classify_question
  ↓
retrieve
  ↓
rerank
  ↓
grade_documents
  ├─ retry → rewrite_query → retrieve
  └─ pass → generate_answer
                    ↓
             grade_answer
              ├─ retry
              └─ END
```

처음부터 멀티 에이전트 구조로 확장하기보다는 위 단일 그래프부터 구현하는 것이 현실적이다.

## 결론

LangGraph는 새로운 RAG 구현체라기보다 현재 구현된 검색·reranking·평가 기능을 연결하는 **상태 관리 및 의사결정 계층**으로 사용하는 것이 좋다.

가장 우선순위가 높은 확장은 다음 세 가지다.

1. 질문 유형별 Adaptive RAG 라우팅
2. 문서 및 답변 근거성 검증과 자동 재시도
3. PostgreSQL checkpointer를 활용한 대화 메모리와 실행 재개

## 참고 문서

- [LangGraph 공식 저장소](https://github.com/langchain-ai/langgraph)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Human-in-the-loop Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- [LangGraph Adaptive RAG 예제](https://github.com/langchain-ai/langgraph/blob/main/examples/rag/langgraph_adaptive_rag.ipynb)
