# 변경 이력

## Unreleased

### Added

- 실제 compiled LangGraph 실행 경로와 검색·재작성·생성·검증·제한된 재시도 노드.
- LLM Tool Calling 기반 `SearchLaw`, `GetArticle` 선택과 Pydantic 인자 검증.
- Tool Calling 미지원 엔드포인트를 위한 결정적 라우팅 복구.
- 답변 필수값·출처·인용 ID 검증.
- TXT, XML, 텍스트 PDF, PNG, JPEG 추출 API.
- LLM 구조화 출력 기반 질문 정보 추출·의도 분류와 문서 요약 API.
- 이전 질문·답변·출처를 이용한 후속 질문 독립 질의 재작성과 문맥별 캐시 키.
- 검증된 이전 답변과 출처를 보고서로 내보내는 `CreatePdf` Tool Calling 및 다운로드 경로.
- 이미지 OCR과 파일 크기·형식·빈 파일 검증.
- 요청·모델·도구 사용량 저장용 PostgreSQL 스키마와 추적 자료형.
- 응답의 `status`, `missing_fields`, `request_id` 필드.
- 에이전트 도구·그래프·문서 처리 통합 테스트와 API 가이드.

### Changed

- 검색 결과를 답변 생성에 재사용해 그래프의 중복 검색을 제거했다.
- 답변 캐시는 재작성된 질문 대신 원래 사용자 질문을 키로 사용할 수 있다.
- LangGraph 노드와 조건 함수를 비동기로 통일해 Python 3.14 테스트 종료 지연을 해결했다.

### Known limitations

- 스캔 PDF의 페이지 이미지 OCR 변환은 아직 지원하지 않는다.
- OCR 실행에는 시스템 Tesseract와 해당 언어 데이터가 필요하다.
- PostgreSQL 관측 스키마는 추가했지만 애플리케이션의 영속 기록 연결과 비용 계산은 후속 작업이다.
- 문서 추출 결과의 영구 저장·색인·삭제 수명주기는 아직 제공하지 않는다.
