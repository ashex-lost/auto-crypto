-- Versioned migration; application requests never create or alter tables.
-- Prefixed names avoid silently reinterpreting the earlier prototype schema.
CREATE TABLE sim_control (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  paused INTEGER NOT NULL DEFAULT 1 CHECK (paused IN (0, 1)),
  active_run_id TEXT,
  last_scheduled_ms INTEGER NOT NULL DEFAULT 0,
  last_success_at TEXT,
  last_cron_success_at TEXT,
  last_outcome TEXT,
  successful_ticks INTEGER NOT NULL DEFAULT 0
);
INSERT INTO sim_control (id) VALUES (1);

CREATE TABLE sim_jobs (
  id TEXT PRIMARY KEY CHECK (length(id) BETWEEN 1 AND 64),
  cost_cents INTEGER NOT NULL CHECK (
    typeof(cost_cents) = 'integer' AND cost_cents BETWEEN 1 AND 100000000
  ),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'simulated', 'rejected_budget')),
  created_at TEXT NOT NULL,
  finished_at TEXT,
  run_id TEXT,
  per_task_limit_cents INTEGER,
  total_limit_cents INTEGER
);
CREATE INDEX sim_jobs_pending ON sim_jobs (status, created_at, id);
CREATE INDEX sim_jobs_run ON sim_jobs (run_id);

-- These are local failure records, not evidence that a notification was sent.
CREATE TABLE sim_failures (
  code TEXT PRIMARY KEY,
  count INTEGER NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
