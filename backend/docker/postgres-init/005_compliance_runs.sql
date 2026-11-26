BEGIN;

-- 컴플라이언스 에이전트 실행 기록. 진행 상태와 최종 판정, 승인 결과를 남긴다.
-- 그래프 중간 상태(메시지, 근거 원문)는 LangGraph 체크포인트 테이블에 thread_id로 저장된다.
CREATE TABLE IF NOT EXISTS compliance_runs (
    id uuid PRIMARY KEY,
    thread_id varchar(100) NOT NULL UNIQUE,
    status varchar(30) NOT NULL,
    source_type varchar(10) NOT NULL DEFAULT 'text',
    filename varchar(255),
    description_hash char(64) NOT NULL,
    high_impact varchar(10),
    confidence double precision,
    assessment jsonb,
    review jsonb,
    report_url text,
    error_code varchar(100),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_compliance_runs_status_created ON compliance_runs (status, created_at DESC);

COMMIT;
