BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email varchar(320) UNIQUE,
    display_name varchar(100),
    status varchar(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'disabled')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE chat_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    anonymous_key varchar(100) UNIQUE,
    title varchar(200),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CHECK (user_id IS NOT NULL OR anonymous_key IS NOT NULL)
);

CREATE TABLE messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    reply_to_id uuid REFERENCES messages(id) ON DELETE SET NULL,
    role varchar(20) NOT NULL CHECK (role IN ('user', 'assistant')),
    content text NOT NULL,
    status varchar(20) NOT NULL DEFAULT 'completed'
        CHECK (status IN ('pending', 'completed', 'failed')),
    error_detail jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE law_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    law_id varchar(50) NOT NULL UNIQUE,
    mst varchar(50),
    name varchar(300) NOT NULL,
    abbreviation varchar(100),
    law_type varchar(50),
    department varchar(100),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE law_versions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    law_document_id uuid NOT NULL REFERENCES law_documents(id) ON DELETE CASCADE,
    promulgation_date date,
    effective_date date NOT NULL,
    promulgation_number varchar(50),
    amendment_type varchar(50),
    source_file varchar(500),
    source_checksum varchar(128) NOT NULL UNIQUE,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (law_document_id, effective_date, promulgation_number)
);

CREATE TABLE ingestion_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    law_version_id uuid NOT NULL REFERENCES law_versions(id) ON DELETE CASCADE,
    collection_name varchar(200) NOT NULL,
    chunking_strategy varchar(100) NOT NULL,
    embedding_model varchar(100) NOT NULL,
    total_chunks integer CHECK (total_chunks >= 0),
    searchable_chunks integer CHECK (searchable_chunks >= 0),
    status varchar(20) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed')),
    error_message text,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE TABLE rag_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_message_id uuid NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
    assistant_message_id uuid UNIQUE REFERENCES messages(id) ON DELETE SET NULL,
    law_version_id uuid REFERENCES law_versions(id) ON DELETE SET NULL,
    method varchar(100) NOT NULL,
    collection_name varchar(200) NOT NULL,
    top_k integer NOT NULL CHECK (top_k > 0),
    candidate_k integer NOT NULL CHECK (candidate_k > 0),
    used_reranking boolean NOT NULL DEFAULT false,
    abstained boolean,
    elapsed_ms integer CHECK (elapsed_ms >= 0),
    model_config jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE retrieval_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rag_run_id uuid NOT NULL REFERENCES rag_runs(id) ON DELETE CASCADE,
    qdrant_point_id uuid,
    chunk_key varchar(200),
    rank integer NOT NULL CHECK (rank > 0),
    article varchar(30),
    paragraph varchar(30),
    item varchar(30),
    subitem varchar(30),
    title varchar(300),
    dense_score double precision,
    bm25_score double precision,
    rrf_score double precision,
    rerank_score double precision,
    payload_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (rag_run_id, rank)
);

CREATE TABLE answer_sources (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    assistant_message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    retrieval_result_id uuid REFERENCES retrieval_results(id) ON DELETE SET NULL,
    source_label varchar(20) NOT NULL,
    display_order integer NOT NULL CHECK (display_order > 0),
    content_snapshot text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (assistant_message_id, source_label),
    UNIQUE (assistant_message_id, display_order)
);

CREATE TABLE answer_evaluations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rag_run_id uuid NOT NULL REFERENCES rag_runs(id) ON DELETE CASCADE,
    evaluator_type varchar(20) NOT NULL
        CHECK (evaluator_type IN ('human', 'llm_judge')),
    evaluator_name varchar(100),
    correctness smallint NOT NULL CHECK (correctness BETWEEN 0 AND 2),
    relevance smallint NOT NULL CHECK (relevance BETWEEN 0 AND 2),
    faithfulness smallint NOT NULL CHECK (faithfulness BETWEEN 0 AND 2),
    hallucination boolean NOT NULL,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE answer_feedback (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id uuid REFERENCES users(id) ON DELETE SET NULL,
    rating smallint NOT NULL CHECK (rating IN (-1, 1)),
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_chat_sessions_user_updated
    ON chat_sessions (user_id, updated_at DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX ix_messages_session_created ON messages (session_id, created_at);
CREATE INDEX ix_rag_runs_created ON rag_runs (created_at DESC);
CREATE INDEX ix_retrieval_results_run_rank ON retrieval_results (rag_run_id, rank);
CREATE INDEX ix_answer_evaluations_run ON answer_evaluations (rag_run_id, evaluator_type);
CREATE INDEX ix_law_versions_document_effective
    ON law_versions (law_document_id, effective_date DESC);

COMMIT;
