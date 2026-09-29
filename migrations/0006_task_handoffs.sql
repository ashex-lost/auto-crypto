CREATE TABLE IF NOT EXISTS task_handoffs (
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, digest TEXT NOT NULL,
 plan TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending_approval','approved','completed','rejected','expired')),
 created_at INTEGER NOT NULL, approved_at INTEGER, completed_at INTEGER, evidence TEXT
);
CREATE INDEX IF NOT EXISTS task_handoffs_state ON task_handoffs(state,created_at);
