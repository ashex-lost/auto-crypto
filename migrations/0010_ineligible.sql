-- Projects you could not join (account/region rejected). Similar future activities are skipped.
CREATE TABLE IF NOT EXISTS ineligible_keys (
 key TEXT PRIMARY KEY, reason TEXT, example_id TEXT, at INTEGER NOT NULL
);
