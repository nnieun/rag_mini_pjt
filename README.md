# AI 기본법 근거 기반 RAG

법률을 잘 모르는 사용자도 자연어 질문을 통해 **인공지능 발전과 신뢰 기반 조성 등에 관한 기본법**을 이해할 수 있도록 만드는 근거 기반 QA 프로젝트다.

국가법령정보센터 Open API에서 법령 XML을 수집하고, 법률 구조에 맞게 청킹하여 Qdrant에 저장한다. 이후 Dense Search, BM25, RRF, Qwen Reranking을 비교하고, 검색된 법률 원문만 사용해 답변과 출처를 생성한다.

> 대상 법령: 인공지능 발전과 신뢰 기반 조성 등에 관한 기본법  
> 시행: 2026년 7월 21일  
> 법률: 제21311호, 2026년 1월 20일 일부개정  
> 법령 일련번호(MST): `282791`

프로젝트 진행 중 발생한 오류, 실패한 접근, 해결 과정은 [시행착오 기록](docs/TRIALS_AND_ERRORS.md)에 정리되어 있다.

## 1. 목표와 전체 흐름

```text
법령 XML 수집
    ↓
법률 구조 분석 및 적응형 청킹
    ↓
Embedding 및 Qdrant 저장
    ↓
Dense + BM25 + RRF 검색
    ↓
선택적 Qwen Reranking
    ↓
근거 기반 답변과 출처 생성
    ↓
Retrieval 및 Answer 평가
```

핵심 질문은 다음과 같다.

- 필요한 법률 조항을 검색했는가?
- 정답 조문을 검색 결과 상단에 배치했는가?
- 답변의 모든 핵심 주장이 검색된 원문으로 뒷받침되는가?
- 검색 개선이 실제 평가 지표 향상으로 이어졌는가?

## 2. 현재 구현 상태

| 영역 | 상태 | 결과 |
|---|---|---|
| 법령 Open API XML 수집 | 완료 | 전체 법령 XML 저장 |
| XML 구조 분석 | 완료 | 장·절·조·항·호·목 파싱 |
| 적응형 계층 청킹 | 완료 | 118개 청크 생성 |
| Qdrant 저장 | 완료 | `ai_basic_law_adaptive_anchor_v1` |
| Dense Retrieval | 완료 | OpenAI 호환 Embedding 사용 |
| Hybrid Retrieval | 완료 | Dense + BM25 + RRF |
| Reranking | 완료 | Qwen3-Reranker-0.6B |
| Retrieval 평가 | 완료 | Golden Set 45문항 비교 |
| 근거 기반 답변 | Notebook 검증 완료 | 답변과 `[S1]` 출처 생성 |
| Answer 수동 평가 | 일부 완료 | 1문항 평가 완료 |
| FastAPI `POST /ask` | 완료 | Hybrid 검색 + 답변 + 출처 반환 |

## 3. 프로젝트 구조

```text
rag_mini_pjt_template/
├── app/
│   └── main.py
├── common/
│   ├── ai_model.py
│   ├── config.py
│   └── qdrant.py
├── data/ai_basic_law/
│   ├── ai_basic_law.xml
│   └── law_search_result.xml
├── eval/
│   ├── EVALUATION_GUIDE.md
│   ├── golden_set_v2.jsonl
│   ├── answer_evaluation.csv
│   └── results/
├── notebook/
│   ├── law_api_fetch.ipynb
│   ├── qdrant_test_adaptive_hierarchy_anchor.ipynb
│   └── ai_basic_law_rag_evaluation_1.ipynb
├── split.py
├── pyproject.toml
└── README.md
```

## 4. 법령 데이터 수집

국가법령정보센터 Open API를 사용한다.

1. `lawSearch`로 `인공지능` 관련 법령 목록을 검색한다.
2. 시행일이 `20260721`인 AI 기본법을 선택한다.
3. 법령 일련번호 `282791`로 법령 본문 XML을 조회한다.
4. 응답을 `data/ai_basic_law/ai_basic_law.xml`에 저장한다.

상세 조회 시 `target=eflaw`와 법령 일련번호를 사용한다. API 응답의 최상위 태그가 `법령`이고 하위에 `기본정보`, `조문`, `부칙`, `제개정이유`가 존재하는지 확인했다.

관련 Notebook:

- `notebook/law_api_fetch.ipynb`
- `notebook/law_api_xml_loader.ipynb`

## 5. 청킹 전략 비교

### 5.1 초기 조 단위 청킹

XML의 `조문단위`를 그대로 저장하여 54개 문서를 만들었다.

문제점:

- 장·절 제목이 독립 검색 결과로 섞였다.
- 제2조 정의처럼 긴 조문에 여러 개념이 한꺼번에 들어갔다.
- “고영향 인공지능이란 무엇인가요?” 질문에서 제2조보다 제33조·제35조가 먼저 검색됐다.

### 5.2 조 + 항 청킹

조문 전체와 항을 동시에 저장했다. 긴 조문의 세부 내용 검색은 쉬워졌지만 다음 문제가 있었다.

- `① ①`, `1. 1.`처럼 번호가 중복됐다.
- 제2조는 하나의 항 안에 12개 정의가 있어 여전히 너무 길었다.
- 조문 전체와 항이 같은 내용을 중복 저장했다.

### 5.3 조 + 항 + 호 + 목 전체 계층 청킹

모든 계층을 검색 청크로 저장했을 때 약 400개 이상의 청크가 생성됐다. 제2조제4호와 각 목을 정밀하게 검색할 수 있었지만 동일한 문장이 여러 계층에 반복되고 한 조문의 하위 청크가 Top-K를 점유했다.

### 5.4 선택적 계층 청킹

모든 조, 직접 내용이 있는 항, 필요한 호만 저장하여 약 229개로 줄였다. 중복은 감소했지만 직접 `항내용`이 있는 항의 개별 호가 검색에서 빠질 수 있었다.

### 5.5 최종: 적응형 계층 + Anchor + Parent Retrieval

최종 Notebook:

```text
notebook/qdrant_test_adaptive_hierarchy_anchor.ipynb
```

최종 규칙:

1. 조문 전체가 800자 이하면 조 단위 검색 청크 하나로 유지한다.
2. 800자를 넘으면 전체 조문을 답변 확장용 `parent`로 보존한다.
3. 항 → 호 → 목 순서로 내려가며 800자 이하가 되는 최소 구조 단위를 `child`로 만든다.
4. 긴 항·호의 도입 문장은 `anchor`로 별도 저장한다.
5. 장·절 제목은 독립 청크가 아니라 metadata에 저장한다.
6. `parent`는 검색에서 제외하고 검색 후 전체 조문 확장에 사용한다.
7. 부칙과 제·개정이유는 본문과 구분된 자료 유형으로 저장한다.

최종 청크 분포:

| 구분 | 개수 |
|---|---:|
| 전체 | 118 |
| 검색 가능 `child/anchor` | 111 |
| 답변 확장용 `parent` | 7 |
| Anchor | 1 |

제2조제4호는 다음처럼 분리된다.

```text
제2조 전체 parent
└── 제4호 anchor: "고영향 인공지능"의 정의
    ├── 가목: 에너지 공급
    ├── 나목: 먹는물 생산
    ├── ...
    └── 카목: 대통령령으로 정하는 영역
```

정의 질문에는 Anchor가 검색되고 구체적인 적용 영역 질문에는 각 목이 검색된다.

## 6. Qdrant 저장

최종 컬렉션:

```text
ai_basic_law_adaptive_anchor_v1
```

| Payload | 설명 |
|---|---|
| `chunk_role` | `parent`, `child`, `anchor` |
| `unit_level` | `article`, `paragraph`, `item`, `subitem` |
| `article`, `paragraph`, `item`, `subitem` | 조·항·호·목 위치 |
| `chapter`, `section` | 장·절 문맥 |
| `parent_id`, `parent_point_id` | 전체 조문 연결 정보 |
| `search_enabled` | 벡터 검색 포함 여부 |
| `content` | 법률 원문 |

검색 시 `search_enabled=True` 조건으로 부모를 제외한다.

```python
Filter(
    must=[
        FieldCondition(
            key="search_enabled",
            match=MatchValue(value=True),
        )
    ]
)
```

임베딩 API의 요청 제한에 대응하기 위해 20개 단위 배치와 65초 무한 재시도를 적용했다. 성공한 배치는 유지하고 실패한 현재 배치만 다시 요청한다.

## 7. Retrieval 방법

### Dense

질문 Embedding과 Qdrant 벡터 간 Cosine 유사도를 사용한다.

### Hybrid(C)

```text
Dense Search + BM25 → RRF
```

BM25 입력에는 법령명, 장, 절, 조, 항, 호, 목, 제목과 원문을 포함한다.

### Hybrid + Reranking(C+D)

Hybrid 후보를 `Qwen/Qwen3-Reranker-0.6B`로 재정렬한다.

단일 정의 질문 결과:

| 방법 | 정답 제2조 순위 | Hit@5 | Recall@5 | MRR@5 |
|---|---:|---:|---:|---:|
| Hybrid | 2위 | 1.0 | 1.0 | 0.5 |
| Hybrid+Reranking | 1위 | 1.0 | 1.0 | 1.0 |

## 8. Retrieval 평가

Golden Set은 `eval/golden_set_v2.jsonl`이며 총 45문항이다. 정의, 의무, 절차, 복수 근거, 범위 밖 질문을 포함한다.

- `Hit@5`: Top-5에 정답 조문이 하나라도 있는 비율
- `Recall@5`: 필요한 정답 조문 중 Top-5에서 찾은 비율
- `MRR@5`: 첫 정답 조문의 순위 역수 평균

### 8.1 5문항 예비평가

| 방법 | Hit@1 | Hit@3 | Hit@5 | Recall@5 | MRR |
|---|---:|---:|---:|---:|---:|
| Dense | 0.800 | 1.000 | 1.000 | 1.000 | 0.900 |
| Hybrid | 0.800 | 1.000 | 1.000 | 1.000 | 0.900 |
| Hybrid+Reranking | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

작은 평가에서는 리랭킹이 모든 정답 조문을 1위로 올렸다.

### 8.2 45문항 전체 평가

| 방법 | Hit@5 | Recall@5 | MRR@5 |
|---|---:|---:|---:|
| Dense | 0.8095 | 0.7738 | 0.6702 |
| **Hybrid(C)** | **0.9286** | **0.8929** | 0.7210 |
| Hybrid+Reranking(C+D) | 0.9048 | 0.8810 | **0.8452** |

해석:

- Hybrid는 Dense보다 모든 지표가 개선됐다.
- Reranking은 정답 순위를 개선하여 MRR이 가장 높았다.
- 그러나 일부 정답을 Top-5 밖으로 밀어 Hit@5와 Recall@5는 Hybrid보다 낮았다.
- 검색 누락 방지를 우선하는 현재 기준에서는 **Hybrid(C)**가 최종 Retrieval 방법이다.

> 최종 선택: **Dense + BM25 + RRF 기반 Hybrid Search(C)**

Reranking은 후보 수와 결합 방식을 조정한 후 다시 평가할 수 있다.

## 9. 범위 밖 질문

q41~q45는 법률에서 직접 답할 수 없는 범위 밖 질문이다.

- AI 손해배상
- AI 발명 특허 출원
- 세금 감면
- 기본계획 예산 규모
- 개발자 자격증 시험 요건

이 문항은 관련 조문 Hit보다 시스템이 근거 부족을 인식하고 답변을 거절하는지를 평가해야 한다. 향후 Retrieval 평가와 별도로 `Abstention Accuracy`를 추가한다.

## 10. 근거 기반 답변

검색 결과의 `parent_id`로 전체 조문을 가져와 LLM Context를 구성한다.

- 제공된 법령 근거만 사용한다.
- 핵심 주장 뒤에 `[S1]` 형식으로 출처를 표시한다.
- 근거가 부족하면 확인할 수 없다고 답한다.
- 법률 내용이나 조문을 추측하지 않는다.

## 11. Answer 평가

| 기준 | 0점 | 1점 | 2점 |
|---|---|---|---|
| 정답성 | 핵심 내용이 틀림 | 일부만 맞거나 조건 누락 | 핵심 내용과 조건이 정확함 |
| 관련성 | 질문과 무관함 | 일부 관련되지만 우회적임 | 질문에 직접 답함 |
| 근거 충실성 | 주요 주장이 근거로 지지되지 않음 | 일부 주장만 지지됨 | 모든 핵심 주장이 근거로 지지됨 |

Hallucination은 `있음/없음`으로 별도 기록한다.

현재 수동 평가:

| 질문 | 방법 | 정답성 | 관련성 | 근거 충실성 | Hallucination |
|---|---|---:|---:|---:|---|
| 고영향 인공지능이란 무엇인가요? | Hybrid | 2 | 2 | 2 | 없음 |

결과는 `eval/answer_evaluation.csv`에 저장한다. 현재 1문항만 수동 평가했으므로 Answer 품질을 확정하려면 평가 범위를 확대해야 한다.

## 12. 환경 설정

```bash
uv sync
uv run jupyter lab
```

프로젝트 루트 `.env`:

```dotenv
LAW_API_OC=발급받은_OC

LLM_API_KEY=API_KEY
LLM_BASE_URL=OPENAI_COMPATIBLE_BASE_URL
LLM_MODEL=gpt-5.4-mini
EMBEDDING_MODEL=text-embedding-3-small

QDRANT_URL=http://localhost:6333
```

OpenAI를 직접 사용하면 `OPENAI_API_KEY`를 사용할 수도 있다. `.env`는 Git에 커밋하지 않는다.

## 13. 실행 순서

1. 법령 XML 수집: `notebook/law_api_fetch.ipynb`
2. 최종 청킹 및 저장: `notebook/qdrant_test_adaptive_hierarchy_anchor.ipynb`
3. Retrieval/Answer 평가: `notebook/ai_basic_law_rag_evaluation_1.ipynb`

평가 Notebook은 다음을 수행한다.

1. Qdrant의 검색 청크와 부모 청크를 로딩한다.
2. Dense, Hybrid, Hybrid+Reranking을 실행한다.
3. 45문항의 Hit@5, Recall@5, MRR@5를 계산한다.
4. 검색 근거를 부모 조문으로 확장한다.
5. 답변과 출처를 생성한다.
6. 사람이 Answer 점수를 기록한다.

### FastAPI 실행

```bash
uv run uvicorn app.main:app --reload
```

- API 문서: `http://127.0.0.1:8000/docs`
- 상태 확인: `GET http://127.0.0.1:8000/health`
- 질문: `POST http://127.0.0.1:8000/ask`

## 14. FastAPI QA API

구현 파일:

```text
app/main.py
```

45문항 Retrieval 평가에서 Hit@5와 Recall@5가 가장 높았던 **Hybrid(C)**를 API의 기본 검색 방법으로 사용한다. API에는 Qwen Reranking을 적용하지 않았다.

### 14.1 요청 처리 흐름

```text
POST /ask
    ↓
질문 Embedding 생성
    ↓
Qdrant Dense 후보 검색
    +
BM25 키워드 후보 검색
    ↓
RRF 순위 결합
    ↓
parent_id로 전체 조문 확장
    ↓
LLM 근거 기반 답변 생성
    ↓
Answer + Sources 반환
```

서버가 시작될 때 Qdrant에서 청크를 한 번 로딩하고 BM25 인덱스를 생성한다. 요청마다 청크 전체를 다시 읽지 않으며, 동일한 질문의 Embedding은 메모리에 캐시한다.

### 14.2 엔드포인트

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/` | API 기본 정보 |
| `GET` | `/health` | Qdrant 컬렉션과 로딩된 청크 상태 |
| `POST` | `/ask` | 질문 검색 및 근거 기반 답변 생성 |
| `GET` | `/docs` | Swagger UI |

상태 확인:

```bash
curl http://127.0.0.1:8000/health
```

응답 예시:

```json
{
  "status": "ok",
  "collection": "ai_basic_law_adaptive_anchor_v1",
  "searchable_chunks": 111,
  "total_chunks": 118
}
```

### 14.3 질문 요청

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"고영향 인공지능이란 무엇인가요?"}'
```

요청 형식:

```json
{
  "question": "고영향 인공지능이란 무엇인가요?"
}
```

응답 형식:

```json
{
  "answer": "고영향 인공지능이란 ... [S2]",
  "sources": [
    {
      "source_id": "S2",
      "article": "제2조",
      "paragraph": "",
      "item": "",
      "subitem": "",
      "title": "정의",
      "content": "제2조(정의) ..."
    }
  ],
  "method": "Hybrid(Dense+BM25+RRF)",
  "elapsed_ms": 5516.96
}
```

`sources`에는 검색된 하위 청크가 아니라 `parent_id`로 확장한 전체 조문이 들어간다. 답변의 `[S1]`, `[S2]` 표시는 각 `source_id`와 대응한다.

### 14.4 오류 및 요청 제한 처리

- 질문은 2자 이상 1,000자 이하로 검증한다.
- 관련 검색 결과가 없으면 `404`를 반환한다.
- Embedding 또는 LLM 처리 오류는 `502`로 반환한다.
- 429 Rate Limit은 기본 65초 대기 후 최대 3회 재시도한다.
- 질문에 대한 법률 근거가 부족하면 LLM이 추측하지 않고 확인할 수 없다고 답하도록 지시한다.

다음 환경변수로 API 동작을 조정할 수 있다.

```dotenv
QDRANT_COLLECTION_NAME=ai_basic_law_adaptive_anchor_v1
RAG_TOP_K=5
RAG_CANDIDATE_K=20
RAG_RRF_K=60
RAG_RETRY_WAIT_SECONDS=65
RAG_MAX_RETRIES=3
```

### 14.5 실제 동작 검증

로컬 Qdrant와 LLM을 연결해 다음 항목을 확인했다.

| 검증 항목 | 결과 |
|---|---|
| 애플리케이션 시작 | 성공 |
| Qdrant 컬렉션 로딩 | 성공 |
| 검색 청크 | 111개 |
| 전체 청크 | 118개 |
| `GET /health` | `200 OK` |
| `POST /ask` | `200 OK` |
| 대표 질문 응답 시간 | 약 5.5초 |
| 정의 근거 | 제2조 |
| 답변 출처 표시 | `[S1]`, `[S2]` 형식 |

## 15. 실험 Notebook 비교

| Notebook | 목적 |
|---|---|
| `law_api_fetch.ipynb` | 법령 검색 및 전체 XML 저장 |
| `qdrant_test.ipynb` | 초기 조 단위 청킹 |
| `qdrant_test_article_paragraph.ipynb` | 조 + 항 실험 |
| `qdrant_test_hierarchical.ipynb` | 조·항·호·목 전체 계층 실험 |
| `qdrant_test_article_paragraph_item_1.ipynb` | 선택적 계층 실험 |
| `qdrant_test_adaptive_hierarchy_anchor.ipynb` | 최종 적응형 청킹 및 저장 |
| `ai_basic_law_hybrid_rerank.ipynb` | Hybrid/Reranking 초기 실험 |
| `ai_basic_law_rag_evaluation_1.ipynb` | 최종 Retrieval/Answer 평가 |

## 16. 결론

1. 법률 문서는 글자 수보다 조·항·호·목 구조를 우선해야 한다.
2. 모든 계층을 벡터화하면 검색 결과 중복이 증가한다.
3. 짧은 조문은 유지하고 긴 조문만 필요한 깊이로 분해하는 적응형 청킹이 적합하다.
4. 긴 정의나 목록의 도입 문장은 Anchor로 보존해야 한다.
5. Dense보다 Dense + BM25 + RRF Hybrid가 효과적이었다.
6. Reranking은 MRR을 높였지만 현재 설정에서는 Hit@5와 Recall@5를 조금 낮췄다.
7. 현재 최종 Retrieval 선택은 Hybrid(C)다.
8. 검색 성능과 별개로 Answer의 근거 충실성과 Hallucination을 평가해야 한다.

## 17. 다음 작업

- Notebook 코드를 `rag/loader.py`, `chunker.py`, `vectorstore.py`, `retriever.py`, `reranker.py`, `pipeline.py`로 모듈화
- 범위 밖 질문의 Abstention Accuracy 추가
- 전체 Golden Set Answer 평가
- MRR 향상을 유지하면서 Hit@5 하락을 줄이는 Reranking 개선
- 응답에 조·항·호·목 및 법령 원문 링크 포함

## 18. 시행착오 목록 

- [TRIALS_AND_ERRORS.md](/home/aiuser/rag_mini_pjt_template/docs/TRIALS_AND_ERRORS.md)

