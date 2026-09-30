-- Table for persistent agent memories (learned preferences, facts, workflows)

CREATE TABLE IF NOT EXISTS agent_memories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
  category TEXT NOT NULL DEFAULT 'general',
  key TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT agent_memories_session_key_uidx UNIQUE (session_id, key)
);

CREATE INDEX IF NOT EXISTS agent_memories_session_idx ON agent_memories (session_id);
