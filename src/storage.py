"""D1 persistence and atomic reservations; no local SQLite files in a Worker."""
import json
from uuid import uuid4
from common import canonical, now, Blocked


def plain(value):
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    from js import JSON
    return json.loads(JSON.stringify(value))


class Store:
    def __init__(self, db):
        self.db = db

    def statement(self, sql, args):
        return self.db.prepare(sql).bind(*args) if args else self.db.prepare(sql)

    async def all(self, sql, *args):
        r = plain(await self.statement(sql, args).all())
        return r["results"]

    async def one(self, sql, *args):
        rows = await self.all(sql, *args)
        return rows[0] if rows else None

    async def run(self, sql, *args):
        return plain(await self.statement(sql, args).run())

    async def batch(self, statements):
        prepared = [self.statement(sql, args) for sql, args in statements]
        try:
            from pyodide.ffi import to_js
            prepared = to_js(prepared)
        except ImportError:
            pass  # CPython tests inject a D1-compatible test database.
        return plain(await self.db.batch(prepared))

    async def acquire(self, timestamp):
        token = uuid4().hex
        rows = await self.all("UPDATE control SET lease_owner=?,lease_until=?,last_tick=? WHERE id=1 AND lease_until<? RETURNING id",
                              token, timestamp+240, timestamp, timestamp)
        return token if rows else None

    async def release(self, token, error=None, cron=False):
        t = now()
        await self.run("UPDATE control SET lease_until=0,lease_owner=NULL,error_code=?,last_success=CASE WHEN ? IS NULL THEN ? ELSE last_success END,last_cron=CASE WHEN ? THEN ? ELSE last_cron END WHERE id=1 AND lease_owner=?",
                       error, error, t, int(cron and error is None), t, token)

    async def event(self, key, kind, payload, proposal_id=None):
        await self.run("INSERT OR IGNORE INTO events(id,kind,proposal_id,payload,created_at) VALUES(?,?,?,?,?)",
                       key, kind, proposal_id, canonical(payload), now())

    async def audit(self, action, target, hash_value=None):
        await self.run("INSERT INTO audit(at,action,target,digest) VALUES(?,?,?,?)", now(), action, target, hash_value)

    async def reserve_ai(self, key, upper, settings, timestamp):
        import datetime
        d = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
        month = int(d.replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp())
        day = int(d.replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
        rows = await self.all("""INSERT INTO costs(id,category,reserved_micro,state,created_at)
            SELECT ?, 'ai', ?, 'reserved', ? WHERE
            (SELECT COALESCE(SUM(COALESCE(actual_micro,reserved_micro)),0) FROM costs WHERE category='ai' AND created_at>=?) + ? <= ?
            AND (SELECT COUNT(*) FROM costs WHERE category='ai' AND created_at>=?) < ?
            AND (SELECT COALESCE(SUM(COALESCE(actual_micro,reserved_micro)),0) FROM costs WHERE category!='capital_and_fee_reservation') + ? <= ?
            AND (SELECT COALESCE(SUM(COALESCE(actual_micro,reserved_micro)),0) FROM costs) + ? <= ?
            RETURNING id""", key, upper, timestamp, month, upper, settings["monthly_ai_usd_micro"], day,
            settings["ai_calls_per_day"], upper, settings["lifetime_cost_usd_micro"],upper,settings["max_loss_usd_micro"])
        if not rows:
            raise Blocked("ai_budget_exhausted")

    async def settle_cost(self, key, actual, evidence):
        await self.run("UPDATE costs SET actual_micro=?,state='confirmed',evidence=? WHERE id=? AND state!='confirmed'", actual, canonical(evidence), key)

    async def uncertain_cost(self, key):
        await self.run("UPDATE costs SET state='uncertain' WHERE id=? AND state='reserved'", key)
