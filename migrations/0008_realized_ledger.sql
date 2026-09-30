-- Realized income, human interventions and periodic deterministic reports.
-- Income rows are only what actually arrived (a tx hash or exchange record), never pools, points or APR.
CREATE TABLE IF NOT EXISTS income (
 id TEXT PRIMARY KEY, source_ref TEXT NOT NULL, opportunity_id TEXT,
 asset TEXT NOT NULL, amount_raw TEXT NOT NULL, decimals INTEGER NOT NULL,
 usd_micro INTEGER NOT NULL CHECK(usd_micro>=0), price_basis TEXT NOT NULL,
 tx_hash TEXT, evidence TEXT, received_at INTEGER NOT NULL, recorded_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS income_time ON income(received_at);
CREATE TABLE IF NOT EXISTS interventions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, kind TEXT NOT NULL,
 target TEXT, opportunity_id TEXT, minutes INTEGER
);
CREATE INDEX IF NOT EXISTS interventions_time ON interventions(at);
ALTER TABLE costs ADD COLUMN opportunity_id TEXT;
ALTER TABLE control ADD COLUMN next_report INTEGER NOT NULL DEFAULT 0;
