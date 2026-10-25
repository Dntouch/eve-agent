import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createBotPresence } from '../../scripts/chatto-presence.mjs';

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
