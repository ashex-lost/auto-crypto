CREATE TABLE IF NOT EXISTS adapter_cursors (
 source TEXT PRIMARY KEY, cursor TEXT
);
CREATE TABLE IF NOT EXISTS task_checks (
 opportunity_id TEXT PRIMARY KEY, checked_at INTEGER NOT NULL,
 status TEXT NOT NULL, result TEXT
);
