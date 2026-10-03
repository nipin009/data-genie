-- Persistent chat memory and dashboard request log. These tables are not part
-- of the dg_ analytics schema, so generated Text-to-SQL cannot access them.
CREATE TABLE IF NOT EXISTS datagenie_sessions (
  conversation_id VARCHAR(80) PRIMARY KEY,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  pending_clarification TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS datagenie_messages (
  message_id VARCHAR(40) PRIMARY KEY,
  conversation_id VARCHAR(80) NOT NULL REFERENCES datagenie_sessions(conversation_id) ON DELETE CASCADE,
  role VARCHAR(20) NOT NULL,
  content TEXT NOT NULL,
  metadata TEXT,
  created_at TIMESTAMP NOT NULL
);
ALTER TABLE datagenie_messages ADD COLUMN IF NOT EXISTS metadata TEXT;

CREATE TABLE IF NOT EXISTS datagenie_request_logs (
  log_id VARCHAR(40) PRIMARY KEY,
  conversation_id VARCHAR(80),
  request_text TEXT NOT NULL,
  classification VARCHAR(40),
  sql_text TEXT,
  selected_tables TEXT,
  row_count INTEGER,
  latency_ms INTEGER,
  status VARCHAR(20) NOT NULL,
  error_text TEXT,
  created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_datagenie_messages_session ON datagenie_messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_datagenie_logs_created ON datagenie_request_logs(created_at);

GRANT SELECT, INSERT, UPDATE ON datagenie_sessions, datagenie_messages, datagenie_request_logs TO datagenie_app;
