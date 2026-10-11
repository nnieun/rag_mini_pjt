BEGIN;

CREATE TABLE IF NOT EXISTS answer_cache (
    cache_key char(64) PRIMARY KEY,
    normalized_question text NOT NULL,
    collection_name varchar(200) NOT NULL,
    pipeline_version varchar(100) NOT NULL,
    response_payload jsonb NOT NULL,
    hit_count bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_answer_cache_expires_at
    ON answer_cache (expires_at);

COMMIT;
