-- Console-editable settings overrides, activity priorities and finished outcomes for EV learning.
CREATE TABLE IF NOT EXISTS settings_overrides (
 id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL, updated_at INTEGER NOT NULL
);
ALTER TABLE opportunities ADD COLUMN ev TEXT;
ALTER TABLE opportunities ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
ALTER TABLE opportunities ADD COLUMN skipped INTEGER NOT NULL DEFAULT 0;
ALTER TABLE opportunities ADD COLUMN outcome TEXT CHECK(outcome IN ('paid','not_paid'));
