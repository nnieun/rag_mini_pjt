BEGIN;

-- 도구 호출이 어느 경로(api: FastAPI /ask, mcp: MCP 서버)로 들어왔는지와
-- 인자 해시(원문 대신 SHA-256)를 남긴다.
ALTER TABLE tool_calls ADD COLUMN IF NOT EXISTS channel varchar(20) NOT NULL DEFAULT 'api';
ALTER TABLE tool_calls ADD COLUMN IF NOT EXISTS arguments_hash char(64);

-- 요청이 들어온 엔드포인트(/ask, mcp:SearchLaw 등)
ALTER TABLE request_runs ADD COLUMN IF NOT EXISTS endpoint varchar(100);

CREATE INDEX IF NOT EXISTS ix_tool_calls_channel_created ON tool_calls (channel, created_at DESC);

COMMIT;
