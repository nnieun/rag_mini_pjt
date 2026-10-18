BEGIN;

CREATE TABLE IF NOT EXISTS request_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid NOT NULL UNIQUE,
    pipeline_version varchar(100) NOT NULL,
    status varchar(30) NOT NULL,
    cache_hit boolean NOT NULL DEFAULT false,
    elapsed_ms double precision,
    error_code varchar(100),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS model_calls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_run_id uuid NOT NULL REFERENCES request_runs(id) ON DELETE CASCADE,
    purpose varchar(50) NOT NULL,
    model_name varchar(150),
    input_tokens integer,
    output_tokens integer,
    total_tokens integer,
    elapsed_ms double precision,
    retry_number integer NOT NULL DEFAULT 0,
    error_code varchar(100),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_run_id uuid NOT NULL REFERENCES request_runs(id) ON DELETE CASCADE,
    tool_name varchar(100) NOT NULL,
    status varchar(30) NOT NULL,
    elapsed_ms double precision,
    error_code varchar(100),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_request_runs_created ON request_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_model_calls_request ON model_calls (request_run_id);
CREATE INDEX IF NOT EXISTS ix_tool_calls_request ON tool_calls (request_run_id);

COMMIT;
