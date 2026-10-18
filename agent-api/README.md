# agent-api

문서 분류·정보 추출을 위한 TypeScript LLM 에이전트. Claude와 OpenAI를 모두 지원하는
공용 Provider 인터페이스로 Tool Calling을 직접 연동하고, Zod로 입출력을 검증하며,
Vitest로 테스트한다. 서버 프레임워크(Hono/NestJS)는 없음 — 라이브러리/CLI 함수 레벨로
핵심 로직만 구현한다.

## 구성

- `src/providers/types.ts` — provider 공용 인터페이스 (`LlmProvider`, `ChatMessage`, `ToolDef`, ...)
- `src/providers/anthropic.ts`, `src/providers/openai.ts` — 각 API 형식을 공용 인터페이스로 매핑
- `src/providers/index.ts` — `LLM_PROVIDER` 환경변수로 provider를 선택하는 팩토리
- `src/schema.ts` — 입력/출력 Zod 스키마 (`AnalyzeInput`, `AnalyzeResult`, ...)
- `src/tools.ts` — Tool Calling 도구 정의 (`lookup_glossary`) 및 실행기
- `src/llm.ts` — provider 비의존적 tool-use 루프, 구조화 출력 검증 (`analyzeDocument`)
- `src/retry.ts` — 429/5xx에 대한 backoff 재시도 (`withRetry`)
- `src/baseline.ts` — 비교용 규칙 기반(키워드) 분류기
- `src/rubric.ts` — 응답 품질 판정 기준(루브릭) 정의
- `src/judge.ts` — LLM 판정자: 루브릭 기준별로 AI 출력을 채점 (`judgeAnswer`)
- `src/agreement.ts` — LLM 판정자 vs 사람 채점 간 일치율·Cohen's kappa 계산
- `src/repeated.ts` — 동일 입력 반복 실행 결과의 통계 요약(Wilson CI)과 두 비율 비교(z-test)
- `eval/` — 평가셋, baseline vs LLM 비교, 판정자-사람 일치도, 반복 측정 비교 스크립트
- `test/` — Vitest 단위 테스트 (LLM 호출은 모두 모킹, 실제 API 미호출)

## 실행

```bash
cd agent-api
pnpm install        # 또는 npm install
cp .env.example .env  # LLM_PROVIDER와 해당 provider의 API 키 입력

pnpm test            # 단위 테스트 (네트워크 호출 없음)
pnpm typecheck
pnpm eval            # 키 설정 시 baseline/LLM 정확도 비교, 미설정 시 baseline만 출력
pnpm eval:judge      # LLM 판정자 vs 사람 채점 일치도
pnpm eval:repeated   # 같은 입력을 N회 반복해 개선 전/후 pass율 통계 비교
```

## Provider 추상화

`LLM_PROVIDER=anthropic|openai` 환경변수로 사용할 모델을 고른다. 나머지 코드
(`analyzeDocument`, `judgeAnswer`, eval 스크립트)는 어떤 provider인지 모른 채
`LlmProvider.chatWithTools()`라는 하나의 메서드만 사용한다.

- `src/providers/types.ts`의 `ChatMessage`/`ToolDef`/`ToolCall`이 두 API의 공통분모를
  표현하는 중립 포맷이다. 각 provider 구현은 이 포맷 ↔ 자신의 wire 포맷(Claude의
  `tool_use`/`tool_result` content block, OpenAI의 `tool_calls`/`role: "tool"` 메시지)을
  양방향으로 변환한다.
- 429/5xx 에러는 provider 구현 내부에서 각 SDK의 에러 타입을 확인해 공용 `TransientError`로
  변환한다. 그 위의 `withRetry()`는 provider와 무관하게 동일하게 동작한다.
- `createProvider()` / `createJudgeProvider()`가 환경변수를 읽어 적절한 provider 인스턴스를
  만든다. 새 provider를 추가하려면 `src/providers/`에 `LlmProvider`를 구현하는 클래스 하나만
  추가하면 되고, `analyzeDocument`/`judgeAnswer`는 수정할 필요가 없다.
- `openai` provider는 공식 OpenAI(`OPENAI_API_KEY`)뿐 아니라 OpenAI 호환 게이트웨이도
  지원한다. `OPENAI_API_KEY`가 없으면 `LLM_API_KEY`/`LLM_BASE_URL`로 폴백한다(이 리포의
  `backend/.env.example`에 있는 `LLM_BASE_URL`/`LLM_API_KEY`와 동일한 네이밍). 예:
  `LLM_BASE_URL=https://monogpt.kr/api/monorouter/v1/`.

## 동작 개요

1. `analyzeDocument(input, provider)`가 문서 텍스트와 추출할 필드 목록을 받는다.
2. 모델에 `lookup_glossary`(용어 조회), `report_analysis`(최종 결과 보고) 두 도구를 제공한다.
3. 모델이 약어를 모르면 `lookup_glossary`를 호출 → 결과를 돌려주고 재호출(최대 4라운드).
4. 모델이 `report_analysis`를 호출하면 그 입력을 `ClassificationResult`/`ExtractionResult` Zod
   스키마로 검증한다. 검증 실패·도구 미호출·라운드 초과는 각각 `failed` 상태와 에러 메시지로 반환한다.
5. 429/5xx 응답은 `TransientError`로 변환되어 `withRetry`가 지수 backoff로 최대 3회 재시도한다.

## 평가

### 1. 정확도 비교 (`pnpm eval`)

`eval/dataset.jsonl`에 카테고리가 라벨링된 16개 문서가 있다. 일부는 요청 필드가 원문에
실제로 없는 경우를 포함해, `field_completeness` 평가에 음성(0점) 사례가 생기도록 구성했다.
규칙 기반 baseline과 LLM 분류 정확도를 같은 데이터셋에서 비교해 출력한다. API 키가 없으면
baseline만 실행된다.

`pnpm eval:generate`는 고정된 `baseline_outputs.jsonl`을 만들 때 쓴다. 매번 같은 데이터셋에
대해 **실제 LLM 호출로** 출력을 생성해 저장하며, `eval:judge`가 판정하는 대상은 이 파일이지
가짜로 작성한 출력이 아니다.

### 2. LLM 판정자 vs 사람 채점 (`pnpm eval:judge`)

LLM 응답은 정답이 하나로 정해지지 않는 경우(요약, 근거 충실성 등)가 많아 단순 정확도만으로는
품질을 측정하기 어렵다. 이를 위해 2단계 평가 체계를 둔다.

1. **판정 기준(루브릭)** — `src/rubric.ts`에 4개 기준을 정의한다: 분류 정확성, 필드 완전성,
   근거 충실성(원문에 없는 내용을 지어내지 않았는지), 분류 근거 설명의 타당성.
2. **LLM 판정자** — `judgeAnswer()`가 `createJudgeProvider()`로 선택된 더 상위 모델
   (Claude는 `ANTHROPIC_JUDGE_MODEL` 기본 `claude-opus-5-5`, OpenAI는
   `OPENAI_JUDGE_MODEL` 기본 `gpt-4o`)에 원문·요청 필드·AI 출력을 주고 루브릭 기준마다
   0/1과 근거를 `submit_judgment` 도구로 반환하게 한다.
3. **사람 채점 대조** — `eval/human_scores.jsonl`에 동일한 고정 출력(`eval/baseline_outputs.jsonl`)에
   대해 사람이 직접 매긴 기준별 점수를 저장해둔다. 판정자와 사람이 **같은 입력·같은 출력**을
   보고 채점해야 공정하게 비교되므로, 매번 새로 생성한 출력이 아니라 고정된 출력을 기준으로 삼는다.
4. `computeAgreement()`가 기준별로 일치율과 Cohen's kappa를 계산해 "LLM 판정자를 얼마나
   신뢰할 수 있는지"를 수치로 보여준다. kappa가 낮은 기준은 루브릭 설명을 구체화하거나
   판정자 프롬프트를 수정해야 한다는 신호다.

### 3. 반복 측정 기반 개선 효과 검증 (`pnpm eval:repeated`)

LLM은 같은 입력에도 매번 다른 출력을 낼 수 있다(특히 `temperature > 0`). 한 번의 실행
결과만으로 "개선됐다/아니다"를 판단하면 그 차이가 실제 개선인지 우연한 변동인지 구분할 수
없다. 이를 위해:

1. 같은 입력을 baseline 프롬프트와 개선된 프롬프트로 각각 `N`회(기본 8회, `EVAL_REPEATS`로
   조절) 반복 실행한다.
2. 매 실행 결과를 `judgeAnswer()`의 `overall_pass`로 성공/실패 이진값으로 변환한다.
3. `summarizeBinary()`로 각 그룹의 pass율과 Wilson 95% 신뢰구간을 구하고,
   `compareBinaryRates()`로 두 비율 차이에 대한 z-검정 p-value를 계산한다.
4. `p < 0.05`면 "반복 측정의 노이즈로는 설명되지 않는 유의미한 개선"으로 판단하고, 그렇지
   않으면 표본을 늘리거나 변경을 보류한다.

세 스크립트 모두 선택된 provider의 API 키가 없으면 안내만 출력하고 종료한다. 통계 로직
(`src/agreement.ts`, `src/repeated.ts`)은 LLM 호출 없이 합성 데이터로 단위 테스트가
되어 있다.

### 실측 결과 (2026-10-19, `gpt-4o`)

| 평가 | 결과 |
|---|---|
| `pnpm eval` (분류 정확도, n=16) | baseline(키워드) 81.3% / LLM 81.3% |
| `pnpm eval:judge` — `category_correct` | 일치율 93.8%, kappa 0.82 |
| `pnpm eval:judge` — `field_completeness` | 일치율 100%, kappa 1.00 |
| `pnpm eval:judge` — `groundedness` | 일치율 100%, kappa 1.00 |
| `pnpm eval:judge` — `reason_quality` | 일치율 87.5%, kappa 0.00(2차 검수 점수에 변동이 거의 없어 우연 보정 시 낮게 나옴) |
| `pnpm eval:repeated` (n=15/그룹) | before 100% → after 86.7%, p=0.143 → **유의하지 않음** |

`eval:judge`의 "사람 채점"(`eval/human_scores.jsonl`)은 이 실행에서는 별도의 독립 검수자가
아니라 Claude가 루브릭 기준으로 16개 출력을 직접 대조 검토해 작성했다. 시스템 자체는 실제
사람이 채점한 값을 넣어도 동일하게 동작하지만, 이 결과를 인용할 때는 "LLM 판정자 vs 사람
채점"이 아니라 "LLM 판정자 vs 2차 검수자(Claude)"로 표기해야 정확하다. `eval:repeated`의
"개선 전/후"도 실제 기능 개선이 아니라 prompt instruction 변경 1건에 대한 데모이며, 이번
실행에서는 오히려 개선 프롬프트 쪽 pass율이 낮게 나왔고 그 차이도 통계적으로 유의하지
않았다 — "반복 측정 없이는 한 번의 결과만으로 개선을 단정할 수 없다"는 이 체계의 설계
의도를 보여주는 사례다.
