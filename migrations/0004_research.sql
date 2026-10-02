ALTER TABLE opportunities ADD COLUMN screening TEXT;
ALTER TABLE opportunities ADD COLUMN screening_version TEXT;
CREATE TABLE IF NOT EXISTS model_runs (
 id TEXT PRIMARY KEY, role TEXT NOT NULL, model TEXT NOT NULL,
 prompt_version TEXT NOT NULL, input_hash TEXT NOT NULL, input_snapshot TEXT NOT NULL,
 created_at INTEGER NOT NULL, state TEXT NOT NULL,
 reserved_micro INTEGER NOT NULL, actual_micro INTEGER,
 usage TEXT, result TEXT, error_code TEXT
);
