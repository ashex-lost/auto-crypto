// Cloudflare Worker simulation. There are no outbound requests or wallet calls.
const schema = [
  `CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    cost_cents INTEGER NOT NULL CHECK (cost_cents > 0),
    status TEXT NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending', 'simulated', 'rejected_budget')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
  )`,
  `CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
  )`,
];

export function positiveLimit(value) {
  if (!/^[1-9][0-9]*$/.test(String(value))) {
    throw new Error('Simulation limit must be a positive integer');
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed)) {
    throw new Error('Simulation limit is too large');
  }
  return parsed;
}

export function checkMode(env) {
  if (env.RUN_MODE !== 'simulation') {
    throw new Error('This Worker supports simulation only');
  }
  if (!env.DB) {
    throw new Error('D1 database binding is missing');
  }
  return {
    perTask: positiveLimit(env.SIM_PER_TASK_CENTS),
    total: positiveLimit(env.SIM_TOTAL_CENTS),
  };
}

async function initialize(db) {
  for (const statement of schema) {
    await db.prepare(statement).run();
  }
}

export async function tick(env, now = new Date()) {
  const limits = checkMode(env);
  await initialize(env.DB);
  await env.DB.prepare(`INSERT INTO state (key, value) VALUES ('heartbeat', ?)
    ON CONFLICT(key) DO UPDATE SET value=excluded.value`)
    .bind(now.toISOString()).run();

  const paused = await env.DB.prepare(`SELECT value FROM state WHERE key='paused'`).first();
  if (paused?.value === '1') return 'paused';

  const job = await env.DB.prepare(`SELECT id FROM jobs WHERE status='pending'
    ORDER BY created_at, id LIMIT 1`).first();
  if (!job) return 'idle';

  // A single conditional D1 UPDATE checks the aggregate and changes status.
  // This only protects simulated accounting; live side effects require more.
  await env.DB.prepare(`UPDATE jobs SET status = CASE
    WHEN cost_cents <= ? AND
      (SELECT COALESCE(SUM(cost_cents), 0) FROM jobs WHERE status='simulated')
        + cost_cents <= ?
    THEN 'simulated' ELSE 'rejected_budget' END
    WHERE id=? AND status='pending'`)
    .bind(limits.perTask, limits.total, job.id).run();
  const result = await env.DB.prepare(`SELECT status FROM jobs WHERE id=?`)
    .bind(job.id).first();
  return result?.status ?? 'idle';
}

export async function status(env) {
  const limits = checkMode(env);
  await initialize(env.DB);
  const [heartbeat, paused, used, counts] = await Promise.all([
    env.DB.prepare(`SELECT value FROM state WHERE key='heartbeat'`).first(),
    env.DB.prepare(`SELECT value FROM state WHERE key='paused'`).first(),
    env.DB.prepare(`SELECT COALESCE(SUM(cost_cents), 0) AS amount
      FROM jobs WHERE status='simulated'`).first(),
    env.DB.prepare(`SELECT status, COUNT(*) AS count FROM jobs GROUP BY status`).all(),
  ]);
  return {
    mode: 'simulation',
    live_execution: false,
    paused: paused?.value === '1',
    limits_cents: { per_task: limits.perTask, total: limits.total },
    simulated_cost_cents: used?.amount ?? 0,
    job_counts: Object.fromEntries((counts.results ?? []).map(r => [r.status, r.count])),
    heartbeat: heartbeat?.value ?? null,
  };
}

export default {
  async fetch(request, env) {
    if (request.method !== 'GET' || new URL(request.url).pathname !== '/status') {
      return new Response('Not found', { status: 404 });
    }
    return Response.json(await status(env), {
      headers: { 'cache-control': 'no-store' },
    });
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(tick(env));
  },
};
