-- Autonomous agent tables: goals, triggers, and execution log

-- Persistent goals the agent has been given (or created for itself)
CREATE TABLE IF NOT EXISTS agent_goals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'paused', 'completed', 'cancelled')),
    priority    INT  NOT NULL DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
    -- Cron expression (NULL = one-shot or condition-only)
    cron_expr   TEXT,
    -- PowerShell condition: if non-null, goal only fires when this evaluates truthy
    condition_ps TEXT,
    -- Last time this goal was evaluated / ran
    last_run_at  TIMESTAMPTZ,
    next_run_at  TIMESTAMPTZ,
    run_count    INT NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS agent_goals_session_idx
    ON agent_goals (session_id, status);

CREATE INDEX IF NOT EXISTS agent_goals_next_run_idx
    ON agent_goals (next_run_at)
    WHERE status = 'active';

-- Log of every autonomous execution
CREATE TABLE IF NOT EXISTS autonomous_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    goal_id     UUID REFERENCES agent_goals (id) ON DELETE SET NULL,
    trigger_type TEXT NOT NULL DEFAULT 'cron'
                    CHECK (trigger_type IN ('cron', 'condition', 'reflection', 'watchdog', 'manual')),
    prompt      TEXT NOT NULL,
    reply       TEXT,
    success     BOOLEAN NOT NULL DEFAULT true,
    duration_ms INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS autonomous_log_session_idx
    ON autonomous_log (session_id, created_at DESC);
