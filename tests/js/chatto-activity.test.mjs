import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { createBotActivityReporter } from '../../scripts/chatto-activity.mjs';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(predicate) {
  for (let i = 0; i < 200; i++) { if (predicate()) return; await delay(5); }
  assert.fail('Activity did not settle');
}
const target = { server_url: 'https://chat.example', bot_id: 'eve', room_id: 'room', thread_root_id: 'root' };
function fixture(t, options = {}) {
  const requests = [];
  const reporter = createBotActivityReporter({ serverUrl: target.server_url, botId: 'eve', apiKey: 'test-only',
    fetchImpl: async (url, init) => { requests.push({ ...JSON.parse(init.body), signal: init.signal }); return { ok: true }; },
    ...options });
  t.after(() => reporter.stop());
  return { reporter, requests, categories: () => requests.map(r => r.botActivity.replace('BOT_ACTIVITY_', '')) };
}

test('runtime phases, thread targeting, and independent IDLE after cancellation', async t => {
  const controller = new AbortController();
  const { reporter, requests, categories } = fixture(t);
  const handle = reporter.begin(target, 'THINKING', controller.signal);
  await until(() => requests.length === 1);
  for (const activity of ['TOOL_USE', 'THINKING', 'WRITING']) {
    handle.update(activity);
    await until(() => categories().at(-1) === activity);
  }
  controller.abort();
  await until(() => categories().at(-1) === 'IDLE');
  assert.deepEqual(categories(), ['THINKING', 'TOOL_USE', 'THINKING', 'WRITING', 'IDLE']);
  assert.ok(requests.every(r => r.roomId === 'room' && r.threadRootEventId === 'root'));
  assert.equal(requests.at(-1).signal.aborted, false);
});

test('parallel targets and jobs aggregate with web precedence; old completion cannot clear newer work', async t => {
  const { reporter, requests } = fixture(t);
  const first = reporter.begin(target, 'TOOL_USE');
  const second = reporter.begin(target, 'WEB_RESEARCH');
  const other = reporter.begin({ ...target, thread_root_id: 'other' }, 'WRITING');
  await until(() => requests.some(r => r.botActivity === 'BOT_ACTIVITY_WEB_RESEARCH') && requests.some(r => r.threadRootEventId === 'other'));
  first.end();
  await delay(10);
  assert.equal(requests.some(r => r.botActivity === 'BOT_ACTIVITY_IDLE'), false);
  const third = reporter.begin(target, 'TOOL_USE');
  second.end();
  await until(() => requests.filter(r => r.threadRootEventId === 'root').at(-1).botActivity === 'BOT_ACTIVITY_TOOL_USE');
  third.end(); other.end();
  await until(() => requests.filter(r => r.botActivity === 'BOT_ACTIVITY_IDLE').length === 2);
});

test('requests serialize and obsolete intermediate phases coalesce before IDLE', async t => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const requests = [];
  let active = 0, peak = 0;
  const { reporter } = fixture(t, { fetchImpl: async (url, init) => {
    active++; peak = Math.max(peak, active);
    requests.push(JSON.parse(init.body));
    if (requests.length === 1) await gate;
    active--;
    return { ok: true };
  } });
  const handle = reporter.begin(target);
  await until(() => requests.length === 1);
  handle.update('TOOL_USE'); handle.update('WEB_RESEARCH'); handle.update('WRITING'); handle.end();
  assert.equal(requests.length, 1);
  release();
  await reporter.stop();
  assert.equal(peak, 1);
  assert.deepEqual(requests.map(r => r.botActivity), ['BOT_ACTIVITY_THINKING', 'BOT_ACTIVITY_IDLE']);
});

test('acceptance hands input activity to the durable job without an intermediate IDLE', async t => {
  const { reporter, requests, categories } = fixture(t);
  await reporter.withWork(target, async () => {
    await until(() => requests.length === 1);
    reporter.acceptJob('accepted', target);
  });
  await delay(10);
  assert.deepEqual(categories(), ['THINKING']);
  reporter.syncJobs([{ id: 'accepted', target, state: 'running', progress: { bot_activity: 'WRITING' } }]);
  await until(() => categories().at(-1) === 'WRITING');
  reporter.syncJobs([{ id: 'accepted', target, state: 'completed' }]);
  await until(() => categories().at(-1) === 'IDLE');
});

test('late validation never dispatches a superseded state; revoked/foreign targets publish nothing', async t => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const { reporter, requests } = fixture(t, { validate: () => gate });
  const handle = reporter.begin(target);
  handle.end(); release();
  await reporter.stop();
  assert.deepEqual(requests.map(r => r.botActivity), ['BOT_ACTIVITY_IDLE']);
  const denied = fixture(t, { validate: async () => { throw Error('Denied'); } });
  denied.reporter.begin(target);
  denied.reporter.begin({ ...target, bot_id: 'human' });
  denied.reporter.begin({ ...target, server_url: 'https://other.example' });
  await delay(10);
  assert.equal(denied.requests.length, 0);
});

test('heartbeats stop at end and failed/missing bridge snapshots expire', async t => {
  const { reporter, requests, categories } = fixture(t, { intervalMs: 10, snapshotTtlMs: 35 });
  reporter.syncJobs([{ id: 'job', state: 'running', target, progress: { bot_activity: 'WEB_RESEARCH' } }]);
  await until(() => requests.length >= 2);
  assert.ok(categories().every(value => value === 'WEB_RESEARCH'));
  await until(() => categories().at(-1) === 'IDLE');
  const count = requests.length;
  await delay(35);
  assert.equal(requests.length, count);
});

test('reconnection and restart use only current active snapshots, including target moves', async t => {
  const { reporter, requests } = fixture(t);
  const job = { id: 'job', state: 'running', target, progress: { bot_activity: 'TOOL_USE' } };
  reporter.syncJobs([job]);
  await until(() => requests.length === 1);
  reporter.setConnected(false);
  await until(() => requests.at(-1).botActivity === 'BOT_ACTIVITY_IDLE');
  reporter.syncJobs([job]); // A late bridge response during disconnect is ignored.
  reporter.setConnected(true);
  await delay(10);
  assert.equal(requests.length, 2);
  reporter.syncJobs([{ ...job, target: { ...target, thread_root_id: 'new-root' } }]);
  await until(() => requests.at(-1).threadRootEventId === 'new-root');
  reporter.syncJobs([{ ...job, state: 'failed' }]);
  await until(() => requests.at(-1).botActivity === 'BOT_ACTIVITY_IDLE');
  const restarted = fixture(t);
  restarted.reporter.syncJobs([{ ...job, state: 'interrupted' }]);
  await delay(10);
  assert.equal(restarted.requests.length, 0);
});

test('network errors and aborted work never prevent the answer; shutdown clears each target once', async t => {
  const controller = new AbortController();
  const calls = [];
  const { reporter } = fixture(t, { signal: controller.signal, timeoutMs: 15,
    fetchImpl: async (url, init) => {
      const body = JSON.parse(init.body);
      calls.push(body);
      if (body.botActivity === 'BOT_ACTIVITY_IDLE') return { ok: true };
      return new Promise((resolve, reject) => init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true }));
    } });
  assert.equal(await reporter.withWork(target, async () => 'answer'), 'answer');
  await until(() => calls.some(r => r.botActivity === 'BOT_ACTIVITY_IDLE'));
  reporter.begin({ ...target, thread_root_id: '' });
  await until(() => calls.some(r => !r.threadRootEventId));
  controller.abort();
  await Promise.all([reporter.stop(), reporter.stop()]);
  assert.equal(calls.filter(r => r.botActivity === 'BOT_ACTIVITY_IDLE').length, 2);
  const count = calls.length;
  reporter.syncJobs([{ id: 'stale', target, state: 'running' }]);
  await delay(20);
  assert.equal(calls.length, count);
});

test('Connect JSON contract on a local HTTP server carries only target IDs and category', async t => {
  const received = [];
  const server = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    received.push({ url: req.url, headers: req.headers, body: JSON.parse(body) });
    res.writeHead(received.length === 1 ? 403 : 200, { 'Content-Type': 'application/json' });
    res.end('{}');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => { server.closeAllConnections(); server.close(resolve); }));
  const serverUrl = `http://127.0.0.1:${server.address().port}`;
  const reporter = createBotActivityReporter({ serverUrl, botId: 'eve', apiKey: 'local-test-key' });
  t.after(() => reporter.stop());
  const handle = reporter.begin({ ...target, server_url: serverUrl, thread_root_id: '', message_id: 'NOT-A-ROOT',
    conversation_id: 'NOT-A-ROOT-EITHER', integration: 'PRIVATE', url: 'PRIVATE' });
  await until(() => received.length === 1);
  handle.update('WRITING');
  await until(() => received.length === 2);
  handle.end();
  await reporter.stop();
  assert.deepEqual(received.map(r => r.body), ['THINKING', 'WRITING', 'IDLE'].map(activity => ({
    roomId: 'room', botActivity: `BOT_ACTIVITY_${activity}`,
  })));
  for (const request of received) {
    assert.equal(request.url, '/api/connect/chatto.api.v1.RoomService/RefreshTypingIndicator');
    assert.equal(request.headers.authorization, 'Bearer local-test-key');
    assert.equal(request.headers['connect-protocol-version'], '1');
    assert.equal(request.headers['content-type'], 'application/json');
  }
});
