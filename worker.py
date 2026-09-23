"""Simulation only. No network requests, model calls or wallet access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import threading
import time

STOP = threading.Event()


def positive_int(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not an amount")
    result = int(value)
    if str(result) != str(value) or result <= 0:
        raise ValueError("expected a positive integer")
    return result


class Store:
    def __init__(self, directory, per_task=100, total=1000):
        if os.getenv("RUN_MODE", "simulation") != "simulation":
            raise ValueError("This build supports simulation only")
        self.per_task = positive_int(per_task)
        self.total = positive_int(total)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "state.db", timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                digest TEXT NOT NULL,
                cost INTEGER NOT NULL CHECK(cost > 0),
                status TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
        """)

    def close(self):
        self.db.close()

    def enqueue(self, job_id, cost):
        cost = positive_int(cost)
        if not job_id or len(job_id) > 128:
            raise ValueError("job ID must contain 1-128 characters")
        digest = hashlib.sha256(str(cost).encode()).hexdigest()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute(
                "SELECT digest FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row:
                if row[0] != digest:
                    raise ValueError("job ID already exists with different content")
                return False
            self.db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, 'pending', ?)",
                (job_id, digest, cost, time.time()),
            )
        return True

    def tick(self):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute(
                "INSERT OR REPLACE INTO meta VALUES ('heartbeat', ?)",
                (str(time.time()),),
            )
            if (self.directory / "PAUSED").exists():
                return "paused"
            row = self.db.execute(
                "SELECT id, cost FROM jobs WHERE status='pending' "
                "ORDER BY created_at, id LIMIT 1"
            ).fetchone()
            if not row:
                return "idle"
            used = self.db.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM jobs "
                "WHERE status='simulated'"
            ).fetchone()[0]
            job_id, cost = row
            status = (
                "simulated"
                if cost <= self.per_task and used + cost <= self.total
                else "rejected_budget"
            )
            # Simulation has no external side effect. This transaction alone
            # does NOT provide exactly-once execution for future live adapters.
            self.db.execute(
                "UPDATE jobs SET status=? WHERE id=?", (status, job_id)
            )
            return status

    def status(self):
        return {
            "mode": "simulation",
            "paused": (self.directory / "PAUSED").exists(),
            "limits_cents": {"per_task": self.per_task, "total": self.total},
            "simulated_cost_cents": self.db.execute(
                "SELECT COALESCE(SUM(cost), 0) FROM jobs WHERE status='simulated'"
            ).fetchone()[0],
            "job_counts": dict(self.db.execute(
                "SELECT status, COUNT(*) FROM jobs GROUP BY status"
            )),
            "heartbeat": dict(self.db.execute("SELECT key, value FROM meta")),
            "live_execution": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["enqueue", "once", "run", "status"])
    parser.add_argument("--id")
    parser.add_argument("--cost-cents", type=positive_int)
    args = parser.parse_args()
    store = Store(
        os.getenv("DATA_DIR", "data"),
        os.getenv("SIM_PER_TASK_CENTS", "100"),
        os.getenv("SIM_TOTAL_CENTS", "1000"),
    )
    try:
        if args.command == "enqueue":
            if not args.id or args.cost_cents is None:
                parser.error("enqueue requires --id and --cost-cents")
            print(json.dumps({"created": store.enqueue(args.id, args.cost_cents)}))
        elif args.command == "status":
            print(json.dumps(store.status()))
        elif args.command == "once":
            print(json.dumps({"result": store.tick()}))
        else:
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: STOP.set())
            while not STOP.is_set():
                print(json.dumps({"result": store.tick(), **store.status()}), flush=True)
                STOP.wait(30)
    finally:
        store.close()


if __name__ == "__main__":
    main()
