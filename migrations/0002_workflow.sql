CREATE TABLE IF NOT EXISTS control (
 id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 1,
 lease_owner TEXT, lease_until INTEGER NOT NULL DEFAULT 0,
 last_tick INTEGER, last_success INTEGER, last_cron INTEGER,
 next_discovery INTEGER NOT NULL DEFAULT 0, discovery_page INTEGER NOT NULL DEFAULT 0,
 next_review INTEGER NOT NULL DEFAULT 0, error_code TEXT
);
INSERT OR IGNORE INTO control(id) VALUES(1);
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, last_ok INTEGER, last_error TEXT, observed_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS opportunities (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL,
 fingerprint TEXT NOT NULL, data TEXT NOT NULL, observed_at INTEGER NOT NULL,
 analysis TEXT, analyzed_fingerprint TEXT, last_analyzed INTEGER,
 status TEXT NOT NULL DEFAULT 'discovered'
);
CREATE TABLE IF NOT EXISTS proposals (
 id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 plan TEXT NOT NULL, digest TEXT NOT NULL UNIQUE,
 state TEXT NOT NULL DEFAULT 'pending_approval', created_at INTEGER NOT NULL,
 expires_at INTEGER NOT NULL, approved_at INTEGER, error_code TEXT,
 executor_state TEXT, closed_at INTEGER
);
CREATE INDEX IF NOT EXISTS proposals_state ON proposals(state,created_at);
CREATE TABLE IF NOT EXISTS costs (
 id TEXT PRIMARY KEY, category TEXT NOT NULL, proposal_id TEXT,
 reserved_micro INTEGER NOT NULL CHECK(reserved_micro>=0),
 actual_micro INTEGER CHECK(actual_micro>=0),
 state TEXT NOT NULL CHECK(state IN ('reserved','confirmed','uncertain')),
 created_at INTEGER NOT NULL, evidence TEXT
);
CREATE INDEX IF NOT EXISTS costs_date ON costs(created_at);
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, proposal_id TEXT, payload TEXT NOT NULL,
 created_at INTEGER NOT NULL, delivered_at INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
 next_attempt INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reviews (
 id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
 action TEXT NOT NULL, target TEXT NOT NULL, digest TEXT
);
