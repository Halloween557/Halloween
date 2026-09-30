-- Single-user PC agent relay schema.
-- Default session is a fixed UUID so the web app and worker stay aligned.

CREATE TABLE IF NOT EXISTS sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO sessions (id)
VALUES ('00000000-0000-0000-0000-000000000001')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  status TEXT NOT NULL DEFAULT 'offline'
    CHECK (status IN ('online', 'offline'))
);

CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  client_id TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS messages_session_client_id_uidx
  ON messages (session_id, client_id)
  WHERE client_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS messages_session_created_idx
  ON messages (session_id, created_at);

CREATE TABLE IF NOT EXISTS inbox (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'processing', 'done', 'failed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS inbox_status_created_idx
  ON inbox (status, created_at);

CREATE TABLE IF NOT EXISTS pending_actions (
  session_id UUID PRIMARY KEY REFERENCES sessions (id) ON DELETE CASCADE,
  payload JSONB,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_state (
  session_id UUID PRIMARY KEY REFERENCES sessions (id) ON DELETE CASCADE,
  messages JSONB NOT NULL DEFAULT '[]'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
