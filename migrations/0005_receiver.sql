CREATE TABLE IF NOT EXISTS receiver_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at INTEGER NOT NULL,
 status TEXT NOT NULL, chain_id INTEGER, address TEXT, native_raw TEXT,
 assets TEXT, error_code TEXT
);
CREATE INDEX IF NOT EXISTS receiver_snapshots_time ON receiver_snapshots(observed_at DESC);
