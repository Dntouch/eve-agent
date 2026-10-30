import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createBotPresence } from '../../scripts/chatto-presence.mjs';

function fixture({ failWrite = () => false, readActivity } = {}) {
  const writes = [];
  let selected;
  let tick;
  let errors = 0;
  let poll;
  let refreshed = 0;
  const presence = createBotPresence({
    getPresencePreference: async () => ({ preference: selected }),
    setPresencePreference: async request => {
      assert.equal(request.expectedRevision, selected?.revision || '');
      if (failWrite(request.status)) throw Error('network');
      writes.push(request.status);
      selected = { status: request.status, revision: String(writes.length) };
    },
    refreshPresence: async () => { refreshed++; },
  }, {
    schedule: callback => { tick = callback; return 1; }, cancel: () => {},
    onError: () => { errors++; },
    readActivity,
    pollSchedule: (callback, interval) => { assert.equal(interval, 1000); poll = callback; return 2; },
    pollCancel: () => { poll = undefined; },
  });
  return { presence, writes, tick: () => tick(), errors: () => errors,
    refreshed: () => refreshed,
    poll: async () => { const callback = poll; poll = undefined; await callback(); },
    isPolling: () => Boolean(poll),
  };
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test('presence heartbeats do not overwrite preferences; disconnect stops refreshing; shutdown sets offline', async () => {
  const writes = [];
  let refreshed = 0;
  let selected;
  let tick;
  let cancelled = 0;
  const api = {
    getPresencePreference: async () => ({ preference: selected }),
    setPresencePreference: async request => { writes.push(request.status); selected = { status: request.status, revision: 'revision' }; },
    refreshPresence: async () => { refreshed++; },
  };
  const presence = createBotPresence(api, {
    schedule: (callback, interval) => { tick = callback; assert.equal(interval, 30000); return 1; },
    cancel: () => { cancelled++; },
  });
  await presence.setConnected(true);
  await tick();
  await tick();
  assert.deepEqual(writes, [1]);
  assert.equal(refreshed, 3);
  await presence.setConnected(false);
  await tick();
  assert.equal(refreshed, 3);
  assert.equal(cancelled, 1);
  await presence.setConnected(true);
  assert.equal(refreshed, 4);
  await presence.stop();
  assert.deepEqual(writes, [1, 4]);
  await tick();
  assert.equal(refreshed, 4);
});

test('failed presence initialization is retried without interrupting the bot', async () => {
  let tick;
  let errors = 0;
  let reads = 0;
  let writes = 0;
  const presence = createBotPresence({
    getPresencePreference: async () => { if (++reads === 1) throw Error('network'); return {}; },
    setPresencePreference: async () => { writes++; },
    refreshPresence: async () => {},
  }, { schedule: callback => { tick = callback; return 1; }, cancel: () => {}, onError: () => { errors++; } });
  await presence.setConnected(true);
  assert.equal(errors, 1);
  await tick();
  assert.equal(writes, 1);
  await presence.stop();
  assert.equal(writes, 2);
});

test('overlapping requests stay Away until the last answer finishes, without heartbeat rewrites', async () => {
  const { presence, writes, tick } = fixture();
  await presence.setConnected(true);
  const first = deferred(), second = deferred();
  const firstStarted = deferred(), secondStarted = deferred();
  const a = presence.withWork(async () => { firstStarted.resolve(); await first.promise; return 'answer'; });
  await firstStarted.promise;
  const b = presence.withWork(async () => { secondStarted.resolve(); await second.promise; });
  await secondStarted.promise;
  await tick();
  assert.deepEqual(writes, [1, 2]);
  first.resolve();
  assert.equal(await a, 'answer');
  assert.deepEqual(writes, [1, 2]);
  second.resolve();
  await b;
  assert.deepEqual(writes, [1, 2, 1]);
  await tick();
  assert.deepEqual(writes, [1, 2, 1]);
  await presence.stop();
  assert.deepEqual(writes, [1, 2, 1, 4]);
});

test('request errors and cancellation restore Online and preserve the original error', async () => {
  const { presence, writes } = fixture();
  await presence.setConnected(true);
  const controller = new AbortController();
  controller.abort();
  for (const error of [Error('model failed'), controller.signal.reason]) {
    await assert.rejects(presence.withWork(() => { throw error; }), actual => actual === error);
  }
  assert.deepEqual(writes, [1, 2, 1, 2, 1]);
  await presence.stop();
});

test('reconnect preserves working color, and shutdown cannot be undone by a finishing request', async () => {
  const { presence, writes, tick } = fixture();
  await presence.setConnected(true);
  const pending = deferred(), started = deferred();
  const work = presence.withWork(async () => { started.resolve(); await pending.promise; });
  await started.promise;
  await presence.setConnected(false);
  await tick();
  assert.deepEqual(writes, [1, 2]);
  await presence.setConnected(true);
  assert.deepEqual(writes, [1, 2]);
  await presence.stop();
  pending.resolve();
  await work;
  await tick();
  assert.deepEqual(writes, [1, 2, 4]);
});

test('presence failures never repeat work; a heartbeat retries a failed return to Online', async () => {
  let fail;
  const { presence, writes, tick, errors } = fixture({ failWrite: status => status === fail });
  await presence.setConnected(true);
  fail = 2;
  let executions = 0;
  assert.equal(await presence.withWork(async () => { executions++; return 'answer'; }), 'answer');
  assert.equal(executions, 1);
  assert.equal(errors(), 1);
  assert.deepEqual(writes, [1]);
  fail = undefined;
  await presence.withWork(async () => { executions++; fail = 1; });
  assert.deepEqual(writes, [1, 2]);
  assert.equal(executions, 2);
  fail = undefined;
  await tick();
  assert.deepEqual(writes, [1, 2, 1]);
  await presence.stop();
});

test('local work changes color without a Chatto message and idle polls do not refresh presence', async () => {
  let working = false;
  const { presence, writes, poll, refreshed, isPolling } = fixture({ readActivity: async () => ({ working }) });
  await presence.setConnected(true);
  await new Promise(setImmediate);
  assert.deepEqual(writes, [1]);
  const refreshes = refreshed();
  await poll();
  assert.equal(refreshed(), refreshes);
  working = true;
  await poll();
  assert.deepEqual(writes, [1, 2]);
  await presence.withWork(async () => {});
  assert.deepEqual(writes, [1, 2]);
  working = false;
  await poll();
  assert.deepEqual(writes, [1, 2, 1]);
  await presence.stop();
  assert.equal(isPolling(), false);
});

test('ending local work cannot clear an ongoing Chatto request', async () => {
  let working = true;
  const { presence, writes, poll } = fixture({ readActivity: async () => ({ working }) });
  await presence.setConnected(true);
  await new Promise(setImmediate);
  const pending = deferred(), started = deferred();
  const work = presence.withWork(async () => { started.resolve(); await pending.promise; });
  await started.promise;
  working = false;
  await poll();
  assert.equal(writes.at(-1), 2);
  pending.resolve();
  await work;
  assert.equal(writes.at(-1), 1);
  await presence.stop();
});

test('failed and malformed activity reads retain working status and recover on the next poll', async () => {
  let activity = { working: true };
  const { presence, writes, poll, errors } = fixture({ readActivity: async () => {
    if (activity instanceof Error) throw activity;
    return activity;
  } });
  await presence.setConnected(true);
  await new Promise(setImmediate);
  assert.equal(writes.at(-1), 2);
  for (const failure of [Error('EVE temporarily unavailable'), {}, { working: 'false' }]) {
    activity = failure;
    await poll();
    assert.equal(writes.at(-1), 2);
  }
  assert.equal(errors(), 3);
  activity = { working: false };
  await poll();
  assert.equal(writes.at(-1), 1);
  await presence.stop();
});

test('stale activity reads after reconnect or stop cannot change the color or restart polling', async () => {
  const stale = deferred();
  let read = () => stale.promise;
  const { presence, writes, poll, isPolling } = fixture({ readActivity: () => read() });
  await presence.setConnected(true);
  await presence.setConnected(false);
  read = async () => ({ working: false });
  await presence.setConnected(true);
  await new Promise(setImmediate);
  stale.resolve({ working: true });
  await new Promise(setImmediate);
  assert.deepEqual(writes, [1]);
  const late = deferred();
  read = () => late.promise;
  const polling = poll();
  await presence.stop();
  late.resolve({ working: true });
  await polling;
  assert.deepEqual(writes, [1, 4]);
  assert.equal(isPolling(), false);
});
