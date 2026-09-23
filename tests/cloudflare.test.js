import test from 'node:test';
import assert from 'node:assert/strict';
import worker, { positiveLimit, checkMode } from '../src/index.js';

test('simulation-only configuration and positive limits', () => {
  assert.equal(positiveLimit('100'), 100);
  for (const invalid of ['0', '-1', '1.5', 'abc', '9007199254740992']) {
    assert.throws(() => positiveLimit(invalid));
  }
  assert.throws(() => checkMode({ RUN_MODE: 'live', DB: {}, SIM_PER_TASK_CENTS: '1', SIM_TOTAL_CENTS: '1' }));
  assert.throws(() => checkMode({ RUN_MODE: 'simulation', SIM_PER_TASK_CENTS: '1', SIM_TOTAL_CENTS: '1' }));
});

test('no public mutation route', async () => {
  for (const [method, path] of [['POST', '/status'], ['GET', '/enqueue'], ['GET', '/']]) {
    const response = await worker.fetch(new Request(`https://example.com${path}`, { method }), {});
    assert.equal(response.status, 404);
  }
});
