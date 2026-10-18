# AI 기본법 근거 기반 RAG

법률을 잘 모르는 사용자도 자연어 질문을 통해 **인공지능 발전과 신뢰 기반 조성 등에 관한 기본법**을 이해할 수 있도록 만드는 근거 기반 QA 프로젝트다.

국가법령정보센터 Open API에서 법령 XML을 수집하고, 법률 구조에 맞게 청킹하여 Qdrant에 저장한다. 이후 Dense Search, BM25, RRF, 조건부 Qwen Reranking으로 근거를 찾고, 검색된 법률 원문만 사용해 답변과 출처를 생성한다. React 프론트엔드는 후속 대화, 질문 기록, 완료 알림, 근거 원문과 목록형 질문의 추가 조문 보기를 제공한다.

> 대상 법령: 인공지능 발전과 신뢰 기반 조성 등에 관한 기본법  
> 시행: 2026년 7월 21일  
> 법률: 제21311호, 2026년 1월 20일 일부개정  
> 법령 일련번호(MST): `282791`

프로젝트 진행 중 발생한 오류, 실패한 접근, 해결 과정은 [시행착오 기록](docs/TRIALS_AND_ERRORS.md)에 정리되어 있다.

확장 API와 문서 입력 방법은 [API 실행 가이드](docs/API_GUIDE.md), 전체 확장 범위는 [LLM 서비스 확장 기획서](docs/LLM_SERVICE_EXPANSION_PROPOSAL.md), 버전별 변경 사항은 [변경 이력](CHANGELOG.md)을 참고한다. TypeScript 기반 문서 분류·추출 에이전트는 [agent-api/README.md](agent-api/README.md)에서 다룬다.

## 서비스 화면

### 근거 기반 법령 답변

![AI 기본법 법령 검색 서비스 화면](docs/assets/service-screen.png)

화면에는 질문·답변, `[S번호]` 인용, 법령 원문 근거 패널, 검색 과정, 후속 질문 입력과 최근 질문 기록이 함께 나타난다.

### 범위 밖 질문에 대한 답변 거절

![AI 기본법 범위 밖 질문 거절 화면](docs/assets/out-of-scope-after.png)

AI 기본법에서 확인할 수 없는 질문에는 일반 지식으로 답을 만들지 않는다. 정해진 거절 문장만 반환하고 관련 없는 근거 조문도 노출하지 않는다.

## API·RAG 아키텍처

```mermaid
flowchart LR
    user["사용자"] --> frontend["React 법령 검색 UI"]
    frontend -->|"POST /ask"| api["FastAPI"]

    api --> cache{"PostgreSQL 답변 캐시"}
    cache -->|"Cache hit"| frontend
    cache -->|"Cache miss"| classify{"질문 유형 판별"}

    classify -->|"일반형·정의형 Top 5"| scope["검색 범위 결정"]
    classify -->|"목록형 Top 20"| scope

    scope --> embedding["Embedding API"]
    scope --> bm25["In-memory BM25"]
    embedding --> dense["Qdrant Dense Search"]
    qdrant[("Qdrant Vector DB")] --> dense
    dense --> rrf["RRF 결합"]
    bm25 --> rrf

    rrf --> definition{"정의형 질문인가?"}
    definition -->|"Yes"| reranker["Qwen GPU Reranking"]
    definition -->|"No"| parent["Parent 조문 확장"]
    reranker --> parent

    parent --> llm["LLM 근거 기반 답변"]
    llm --> validation["인용·Abstention 검증"]
    validation --> save["PostgreSQL 캐시 저장"]
    save --> api
    api -->|"Answer + Sources"| frontend
```

일반 질문은 `Top-K=5` Hybrid Search를 사용하고, 정의형 질문만 Qwen 리랭킹을 거친다. 목록형 질문은 후보를 최대 20개까지 확장해 관련 조문 수를 계산하고 처음 5개를 우선 표시한다.

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
정의형 질문만 Qwen Reranking
    ↓
목록형 질문은 확장 검색 및 관련 조문 집계
    ↓
근거 기반 답변과 출처 생성
    ↓
PostgreSQL 답변 캐시
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
| 근거 기반 답변 | 모듈화 및 API 검증 완료 | 답변과 `[S1]` 출처 생성 |
| Answer 품질 평가 | 완료 | 10문항 LLM Judge + 사람 검토용 CSV |
| Abstention 평가 | 완료 | 범위 밖 5문항 Accuracy 100% |
| FastAPI `POST /ask` | 완료 | Hybrid 검색, 정의형 조건부 Qwen Reranking, 답변 + 출처 및 목록 메타데이터 반환 |
| PostgreSQL 답변 캐시 | 완료 | 동일 질문의 검색·리랭킹·LLM 호출 재사용, 기본 TTL 30일 |
| 목록형 확장 검색 | 완료 | 관련 조문을 최대 20개까지 탐색하고 5개 우선 표시 |
| 후속 대화 UI | 완료 | 기존 대화에 질문·답변 누적 및 이전 질문 맥락 전달 |
| 답변 완료 알림 | 완료 | 검색 중 새 질문 화면으로 이동해도 완료 알림 및 결과 복원 |
| 근거 없음 처리 | 완료 | 순수 거절 답변은 출처와 근거 패널을 표시하지 않음 |
| 자동 테스트 | 완료 | 청킹·검색·Pipeline·API 20개 통과 |

## 3. 프로젝트 구조

```text
rag_mini_pjt_template/
├── backend/
│   ├── app/
│   ├── common/
│   ├── data/ai_basic_law/
│   ├── eval/
│   ├── rag/
│   ├── scripts/
│   ├── tests/
│   ├── notebook/
│   ├── docker/
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/
├── agent-api/
├── docs/
└── README.md
```

## 4. 법령 데이터 수집

국가법령정보센터 Open API를 사용한다.

1. `lawSearch`로 `인공지능` 관련 법령 목록을 검색한다.
2. 시행일이 `20260721`인 AI 기본법을 선택한다.
3. 법령 일련번호 `282791`로 법령 본문 XML을 조회한다.
4. 응답을 `backend/data/ai_basic_law/ai_basic_law.xml`에 저장한다.

상세 조회 시 `target=eflaw`와 법령 일련번호를 사용한다. API 응답의 최상위 태그가 `법령`이고 하위에 `기본정보`, `조문`, `부칙`, `제개정이유`가 존재하는지 확인했다.

관련 Notebook:

- `backend/notebook/law_api_fetch.ipynb`
- `backend/notebook/law_api_xml_loader.ipynb`

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
backend/notebook/qdrant_test_adaptive_hierarchy_anchor.ipynb
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

임베딩 API의 요청 제한에 대응하기 위해 20개 단위 배치와 설정 가능한 재시도를 적용했다. 성공한 배치는 유지하고 실패한 현재 배치만 다시 요청한다.

Notebook의 최종 로직은 `backend/rag/` 패키지로 분리했다. XML을 다시 인덱싱할 때는 다음 명령을 사용한다. `--recreate`는 기존 컬렉션을 삭제하므로 재생성이 필요한 경우에만 지정한다.

```bash
cd backend
uv run python scripts/index_law.py \
  --collection ai_basic_law_adaptive_anchor_v1 \
  --recreate
```

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

전체 질문에 적용하면 일부 정답 조문을 Top-5 밖으로 밀 수 있어 현재 서비스에서는 정의형 질문에만 조건부로 적용한다. GPU에서 후보 5개, 최대 길이 512, 배치 크기 5로 실행하며 서버 시작 시 모델을 미리 워밍업한다.

단일 정의 질문 결과:

| 방법 | 정답 제2조 순위 | Hit@5 | Recall@5 | MRR@5 |
|---|---:|---:|---:|---:|
| Hybrid | 2위 | 1.0 | 1.0 | 0.5 |
| Hybrid+Reranking | 1위 | 1.0 | 1.0 | 1.0 |

### 목록형 확장 검색

일반 질문은 `Top-K=5`를 유지한다. `관련 조문`, `전체 조문`, `모든 조문`, `정리`, `목록`, `몇 개`처럼 전체 목록을 기대하는 질문은 후보를 최대 20개까지 확장한다.

```text
목록형 질문 감지
    ↓
Hybrid 후보 최대 20개 검색
    ↓
LLM이 직접 관련된 Source ID 선택
    ↓
조문 번호 기준 중복 제거 및 개수 계산
    ↓
5개 우선 표시 + 나머지 N개 조문 보기
```

`total_relevant`는 법률상 절대적인 전체 개수가 아니라 **현재 확장 검색에서 직접 관련성이 확인된 조문 수**다. 법령 규모가 커지면 주체·의무 유형·주제 메타데이터 필터와 `search_id` 기반 페이지네이션으로 확장할 예정이다.

## 8. Retrieval 평가

Golden Set은 `backend/eval/golden_set_v2.jsonl`이며 총 45문항이다. 정의, 의무, 절차, 복수 근거, 범위 밖 질문을 포함한다.

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

> 최종 선택: **Hybrid Search(C)를 기본으로 사용하고 정의형 질문에만 최적화된 Reranking을 적용**

### 8.3 조건부 리랭커 속도 비교

정의형 질문 5문항을 대상으로 GPU에서 후보 수, 입력 길이, 배치 크기를 비교했다.

| 설정 | 후보 수 | max length | batch | Hit@5 | Recall@5 | MRR@5 | Cold | Warm 평균 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 20 | 2048 | 1 | 1.0 | 1.0 | 1.0 | 8,821ms | 608ms |
| Recommended | 10 | 768 | 4 | 1.0 | 1.0 | 1.0 | 5,052ms | 258ms |
| **Max speed** | **5** | **512** | **5** | **1.0** | **1.0** | **1.0** | **4,758ms** | **160ms** |

세 설정의 검색 정확도가 동일하므로 `5개 / 512 / batch 5`를 선택했다. 워밍 상태 평균 시간은 Baseline보다 약 73.6% 감소했다. 모델 최초 로딩에 필요한 Cold 시간은 FastAPI 시작 시 리랭커를 미리 워밍업하여 첫 사용자 요청에서 제외한다.

```env
RAG_RERANK_CANDIDATE_K=5
RAG_RERANK_MAX_LENGTH=512
RAG_RERANK_BATCH_SIZE=5
RAG_RERANK_PRELOAD=true
```

전체 45문항에서는 Hybrid의 Hit@5와 Recall@5가 더 높았기 때문에 모든 질문에 리랭킹하지 않는다. 정의형 질문에만 조건부 리랭킹을 적용해 제2조 정의의 순위를 높이고, 일반 질문은 Hybrid 결과를 그대로 사용한다.

## 9. 답변 품질 및 Abstention 평가

`backend/eval/evaluate_quality.py`는 다음 두 평가를 한 번에 수행한다.

- 답변 가능한 q01~q10: 정답성·관련성·근거 충실성 각 0~2점, Hallucination 여부
- v2 범위 밖 q41~q45: 올바르게 답변을 거절했는지 측정하는 Abstention Accuracy

```bash
cd backend
uv run python eval/evaluate_quality.py --answer-count 10
```

2026-10-11 실행 결과:

| 지표 | 결과 |
|---|---:|
| 평가 답변 수 | 10 |
| 평균 정답성 | 2.0 / 2.0 |
| 평균 관련성 | 2.0 / 2.0 |
| 평균 근거 충실성 | 2.0 / 2.0 |
| Hallucination Rate | 0% |
| 범위 밖 질문 수 | 5 |
| Abstention Accuracy | 100% (5/5) |

결과 파일:

- `backend/eval/results/answer_quality_20261011_015008.csv`
- `backend/eval/results/abstention_20261011_015008.csv`
- `backend/eval/results/quality_summary_20261011_015008.json`

위 답변 평가는 LLM Judge의 자동 점수다. CSV에는 답변, 검색 조문, 전체 근거와 채점 사유가 포함되며 최종 보고 전 사람이 원문과 대조해 확인해야 한다.

## 10. 실행과 테스트

백엔드 실행:

```bash
cd backend
uv run uvicorn app.main:app --reload
```

다른 터미널에서 프론트엔드 실행:

```bash
cd frontend
pnpm install
pnpm dev
```

브라우저에서 `http://localhost:8443`에 접속한다. 개발 환경에서 프론트엔드는 `/api/ask`를 호출하고 Vite가 이를 `http://127.0.0.1:8000/ask`로 전달한다.

배포 환경에서 API 주소가 다르면 `frontend/.env`에 다음 값을 설정한다.

```dotenv
VITE_API_BASE_URL=https://api.example.com
```

이 경우 `backend/.env`의 `FRONTEND_ORIGINS`에도 실제 프론트엔드 Origin을 추가해야 한다.

```dotenv
FRONTEND_ORIGINS=https://example.com
```

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"고영향 인공지능이란 무엇인가요?"}'
```

테스트 실행:

```bash
cd backend
uv run python -m unittest discover -s tests -v
```

현재 20개 테스트가 XML 로딩, 최종 청크 수와 Anchor, 장·절 독립 청크 방지, BM25/RRF/Hybrid 검색, 임베딩 캐시, 부모 확장, 조건부 리랭킹, 목록형 질문 판별, 출처 선택, 순수 Abstention 판정 및 API 스키마를 확인한다. 실제 Qdrant와 LLM을 연결한 `/health`, `/ask` 통합 테스트도 완료했다.

## 11. 범위 밖 질문

q41~q45는 법률에서 직접 답할 수 없는 범위 밖 질문이다.

- AI 손해배상
- AI 발명 특허 출원
- 세금 감면
- 기본계획 예산 규모
- 개발자 자격증 시험 요건

이 문항은 관련 조문 Hit보다 시스템이 근거 부족을 인식하고 답변을 거절하는지를 평가해야 한다. 향후 Retrieval 평가와 별도로 `Abstention Accuracy`를 추가한다.

## 12. 근거 기반 답변

검색 결과의 `parent_id`로 전체 조문을 가져와 LLM Context를 구성한다.

- 제공된 법령 근거만 사용한다.
- 핵심 주장 뒤에 `[S1]` 형식으로 출처를 표시한다.
- 관련 근거가 하나라도 있으면 거절 문구 없이 확인 가능한 내용을 답한다.
- 근거가 전혀 없으면 `제공된 AI 기본법 근거에서는 확인할 수 없습니다.` 한 문장만 반환한다.
- 순수 거절 답변에는 `sources=[]`를 반환하고 근거 패널을 표시하지 않는다.
- 법률 내용이나 조문을 추측하지 않는다.

## 13. Answer 평가

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

결과는 `backend/eval/answer_evaluation.csv`에 저장한다. 현재 1문항만 수동 평가했으므로 Answer 품질을 확정하려면 평가 범위를 확대해야 한다.

## 14. 환경 설정

```bash
cd backend
uv sync
uv run jupyter lab
```

`backend/.env`:

```dotenv
LAW_API_OC=발급받은_OC

LLM_API_KEY=API_KEY
LLM_BASE_URL=OPENAI_COMPATIBLE_BASE_URL
LLM_MODEL=gpt-5.4-mini
EMBEDDING_MODEL=text-embedding-3-small

QDRANT_URL=http://localhost:6333
DATABASE_URL=postgresql://aiuser:local_dev_password@localhost:5432/ai_basic_law

RAG_TOP_K=5
RAG_CANDIDATE_K=20
RAG_LIST_CANDIDATE_K=20
RAG_CONDITIONAL_RERANK=true
RAG_RERANK_CANDIDATE_K=5
RAG_RERANK_MAX_LENGTH=512
RAG_RERANK_BATCH_SIZE=5
RAG_RERANK_PRELOAD=true

RAG_ANSWER_CACHE_ENABLED=true
RAG_CACHE_TTL_DAYS=30
RAG_CACHE_VERSION=conditional-rerank-v8
```

OpenAI를 직접 사용하면 `OPENAI_API_KEY`를 사용할 수도 있다. `.env`는 Git에 커밋하지 않는다.

Qdrant와 PostgreSQL 실행:

```bash
cd backend/docker
docker compose up -d
```

Qdrant가 이미 실행 중이면 `docker compose up -d postgres`로 PostgreSQL만 추가한다. 기존 `qdrant_storage` 볼륨은 유지된다. 초기 PostgreSQL 스키마는 `backend/docker/postgres-init/001_schema.sql`에서 최초 볼륨 생성 시 적용된다.

## 15. 실행 순서

1. 법령 XML 수집: `backend/notebook/law_api_fetch.ipynb`
2. 최종 청킹 및 저장: `backend/notebook/qdrant_test_adaptive_hierarchy_anchor.ipynb`
3. Retrieval/Answer 평가: `backend/notebook/ai_basic_law_rag_evaluation_1.ipynb`

평가 Notebook은 다음을 수행한다.

1. Qdrant의 검색 청크와 부모 청크를 로딩한다.
2. Dense, Hybrid, Hybrid+Reranking을 실행한다.
3. 45문항의 Hit@5, Recall@5, MRR@5를 계산한다.
4. 검색 근거를 부모 조문으로 확장한다.
5. 답변과 출처를 생성한다.
6. 사람이 Answer 점수를 기록한다.

### FastAPI 실행

```bash
cd backend
uv run uvicorn app.main:app --reload
```

- API 문서: `http://127.0.0.1:8000/docs`
- 상태 확인: `GET http://127.0.0.1:8000/health`
- 질문: `POST http://127.0.0.1:8000/ask`

## 16. FastAPI QA API

구현 파일:

```text
backend/app/main.py
```

API는 기본적으로 **Hybrid(C)**를 사용한다. 정의형 질문이면 Hybrid 후보에 Qwen Reranking을 적용하고, 목록형 질문이면 검색 범위를 최대 20개로 확장한다. 동일 질문은 PostgreSQL 캐시에서 반환하며 `refresh=true`로 검색·답변을 다시 생성할 수 있다. `.env`에서 `RAG_CONDITIONAL_RERANK=false`로 조건부 리랭킹을 끌 수 있다.

### 16.1 요청 처리 흐름

```text
POST /ask
    ↓
PostgreSQL 답변 캐시 확인
    ↓ cache miss
질문 Embedding 생성
    ↓
Qdrant Dense 후보 검색
    +
BM25 키워드 후보 검색
    ↓
RRF 순위 결합
    ↓
정의형: 조건부 Qwen Reranking
목록형: 확장 검색 및 관련 Source 판별
    ↓
parent_id로 전체 조문 확장
    ↓
LLM 근거 기반 답변 생성
    ↓
Answer + Sources 반환
```

서버가 시작될 때 Qdrant에서 청크를 한 번 로딩하고 BM25 인덱스를 생성한다. 요청마다 청크 전체를 다시 읽지 않으며, 동일한 질문의 Embedding은 메모리에 캐시한다.

### 16.2 엔드포인트

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

### 16.3 질문 요청

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"고영향 인공지능이란 무엇인가요?"}'
```

요청 형식:

```json
{
  "question": "고영향 인공지능이란 무엇인가요?",
  "refresh": false
}
```

응답 형식:

```json
{
  "answer": "고영향 인공지능이란 ... [S1]",
  "sources": [
    {
      "source_id": "S1",
      "article": "제2조",
      "paragraph": "",
      "item": "",
      "subitem": "",
      "title": "정의",
      "content": "제2조(정의) ..."
    }
  ],
  "method": "Hybrid(Dense+BM25+RRF)+Reranking",
  "retrieved_articles": ["제2조", "제35조", "제33조"],
  "elapsed_ms": 5516.96,
  "cache_hit": false,
  "processing_ms": 5480.21,
  "total_relevant": 1,
  "displayed_count": 1,
  "has_more": false
}
```

`sources`에는 검색된 하위 청크가 아니라 `parent_id`로 확장한 전체 조문이 들어간다. 답변의 `[S1]`, `[S2]` 표시는 각 `source_id`와 대응한다.

목록형 질문에서 관련 조문이 5개를 넘으면 `sources`에는 관련 조문 전체가 포함되고, 프론트엔드는 `displayed_count=5`까지만 먼저 표시한다. `has_more=true`이면 `나머지 N개 조문 보기` 버튼을 제공한다.

### 16.4 오류 및 요청 제한 처리

- 질문은 2자 이상 1,000자 이하로 검증한다.
- 검색 결과가 없거나 법률 근거가 전혀 없으면 `200 OK`와 순수 거절 답변, 빈 `sources`를 반환한다.
- Embedding 또는 LLM 처리 오류는 `502`로 반환한다.
- 429 Rate Limit은 기본 65초 대기 후 최대 3회 재시도한다.
- 질문에 대한 법률 근거가 부족하면 LLM이 추측하지 않고 확인할 수 없다고 답하도록 지시한다.

다음 환경변수로 API 동작을 조정할 수 있다.

```dotenv
QDRANT_COLLECTION_NAME=ai_basic_law_adaptive_anchor_v1
RAG_TOP_K=5
RAG_CANDIDATE_K=20
RAG_LIST_CANDIDATE_K=20
RAG_RRF_K=60
RAG_CONDITIONAL_RERANK=true
RAG_RERANK_CANDIDATE_K=5
RAG_RERANK_MAX_LENGTH=512
RAG_RERANK_BATCH_SIZE=5
RAG_RERANK_PRELOAD=true
RAG_RETRY_WAIT_SECONDS=65
RAG_MAX_RETRIES=3
```

### 16.5 실제 동작 검증

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

### 16.6 프론트엔드 동작

React 프론트엔드는 다음 기능을 제공한다.

- 새 질문과 최근 질문 기록
- 같은 대화 안에서 후속 질문·답변 누적
- 후속 질문 요청 시 최근 질문 맥락 전달
- 처리 중 새 질문 화면으로 이동해도 기존 요청 계속 실행
- 백그라운드 답변 완료 시 인앱 알림 표시 및 결과 복원
- PostgreSQL 캐시 적중 시 기존 처리 시간과 캐시 조회 시간 구분 표시
- 개별 질문 및 전체 질문 기록 삭제 확인
- 답변의 `[S번호]`와 오른쪽 근거 원문 패널 연결
- 순수 거절 답변이면 근거 배지와 근거 패널 숨김
- 목록형 질문은 5개 우선 표시 후 `나머지 N개 조문 보기`

브라우저 탭 제목은 `법령 검색 서비스`이며 법률 저울 파비콘을 사용한다.

## 17. 실험 Notebook 비교

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

## 18. 결론

1. 법률 문서는 글자 수보다 조·항·호·목 구조를 우선해야 한다.
2. 모든 계층을 벡터화하면 검색 결과 중복이 증가한다.
3. 짧은 조문은 유지하고 긴 조문만 필요한 깊이로 분해하는 적응형 청킹이 적합하다.
4. 긴 정의나 목록의 도입 문장은 Anchor로 보존해야 한다.
5. Dense보다 Dense + BM25 + RRF Hybrid가 효과적이었다.
6. Reranking은 전체 적용보다 정의형 질문에 조건부로 적용하는 편이 안정적이었다.
7. 후보 5개·길이 512·배치 5의 GPU 리랭킹은 정확도를 유지하면서 워밍 추론 시간을 약 160ms로 줄였다.
8. 일반 질문은 Hybrid(C), 정의형 질문은 Hybrid+Reranking, 목록형 질문은 확장 Hybrid 검색을 사용한다.
9. Top-K는 전체 관련 조문 개수가 아니므로 목록형 질문은 관련 Source를 별도로 집계해야 한다.
10. 검색 성능과 별개로 Answer의 근거 충실성, Abstention 및 Hallucination을 평가해야 한다.

## 19. 다음 작업

- 목록형 검색을 주체·의무 유형·주제 metadata filtering으로 고도화
- 법령 수가 늘어날 때 `search_id`와 cursor pagination으로 근거 목록 분리
- 후속 질문을 단순 질문 문자열 결합이 아닌 서버 측 대화 세션으로 관리
- 동기 GPU 리랭킹을 작업 스레드로 분리하고 동시 실행 수 제한
- Answer 품질 평가 문항을 전체 Golden Set으로 확대
- 배포 환경용 FastAPI·프론트엔드 컨테이너와 CI 구축

## 20. 시행착오 목록

- [TRIALS_AND_ERRORS.md](docs/TRIALS_AND_ERRORS.md)

## 21. TypeScript Agent API (agent-api/)

`backend/`의 Python/LangGraph RAG와 별개로, `agent-api/`에 TypeScript 기반 문서 분류·정보
추출 에이전트를 구현했다. 서버 프레임워크(Hono/NestJS) 없이 라이브러리/CLI 함수 레벨로
핵심 로직만 구현했고, Claude와 OpenAI(OpenAI-호환 라우터 포함)를 모두 지원하는 공용
Provider 인터페이스로 Tool Calling을 연동한다.

구현 범위:

- **구조화 입출력 검증**: Zod 스키마로 분류·추출 결과 검증 (`src/schema.ts`)
- **Tool Calling**: `lookup_glossary`(용어 조회) 도구를 LLM이 직접 호출하는 루프, 429/5xx
  재시도 (`src/llm.ts`, `src/retry.ts`)
- **Provider 추상화**: `LLM_PROVIDER=anthropic|openai` 환경변수로 전환, OpenAI 쪽은
  `OPENAI_API_KEY` 또는 `LLM_API_KEY`/`LLM_BASE_URL`(OpenAI-호환 게이트웨이) 둘 다 지원
  (`src/providers/`)
- **LLM 판정자 vs 사람 채점 대조**: 루브릭 기반으로 상위 모델이 채점하고, 사람이 매긴
  고정 출력 점수와 일치율·Cohen's kappa를 비교 (`src/judge.ts`, `src/agreement.ts`)
- **반복 측정 기반 개선 검증**: 비결정적 LLM 출력을 N회 반복 실행해 Wilson 신뢰구간과
  두 비율 z-검정으로 개선 전/후 차이가 통계적으로 유의한지 확인 (`src/repeated.ts`)
- **테스트**: Vitest 단위 테스트 37개, LLM 호출은 전부 모킹(실제 네트워크 미호출)

실행 방법과 평가 스크립트(`pnpm eval`, `pnpm eval:judge`, `pnpm eval:repeated`)는
[agent-api/README.md](agent-api/README.md)를 참고한다.
