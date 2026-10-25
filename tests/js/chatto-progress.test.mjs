import { test } from 'node:test';
import assert from 'node:assert/strict';
import { withProgress, threadProgress } from '../../scripts/chatto-progress.mjs';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

test('a long request publishes live progress and one terminal status without repeating work', async () => {
  const events = [];
  let work = 0, reads = 0;
  const result = await withProgress(async () => { work++; await delay(25); return 'answer'; },
    async () => { reads++; return { state: 'working', thread_root_id: 'root' }; },
    async event => { events.push(event); }, { intervalMs: 2 });
  assert.equal(result, 'answer');
  assert.equal(work, 1);
  assert.ok(events.some(event => event.state === 'working'));
  assert.equal(events.at(-1).state, 'completed');
  const stopped = reads;
  await delay(10);
  assert.equal(reads, stopped);
});

test('request failure leaves a terminal failure status; status errors do not fail work', async () => {
  const events = [];
  await assert.rejects(withProgress(async () => { await delay(10); throw Error('failed'); },
    async () => ({ state: 'working', thread_root_id: 'root' }), async event => { events.push(event); }, { intervalMs: 1 }));
  assert.equal(events.at(-1).state, 'failed');
  assert.equal(await withProgress(async () => 'ok', async () => { throw Error('optional'); }, async () => {}), 'ok');
});

test('thread status updates one message and leaves ordinary channel replies alone', async () => {
  const creates = [], updates = [];
  const destination = { roomId: 'room', threadRootId: '' };
  const progress = threadProgress({
    createMessage: async payload => { creates.push(payload); return { message: { id: 'status' } }; },
    updateMessage: async payload => { updates.push(payload); },
  }, destination);
  await progress({ state: 'working', thread_root_id: '' });
  assert.equal(creates.length, 0);
  await progress({ state: 'working', thread_root_id: 'root', integration: 'SolidCraft' });
  await progress({ state: 'working', thread_root_id: 'root', integration: 'SolidCraft' });
  await progress({ state: 'completed', thread_root_id: 'root' });
  assert.equal(creates.length, 1);
  assert.equal(creates[0].threadRootEventId, 'root');
  assert.match(creates[0].body, /SolidCraft/);
  assert.equal(updates.length, 1);
  assert.equal(updates[0].eventId, 'status');
  assert.deepEqual(updates[0].updateMask.paths, ['body']);
  assert.equal(destination.threadRootId, 'root');
});
