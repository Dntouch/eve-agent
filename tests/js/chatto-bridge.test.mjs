import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { setTimeout as delay } from 'node:timers/promises';
import { createEveBridge } from '../../scripts/chatto-bridge.mjs';
import { ChattoState, handleMessage } from '../../scripts/chatto-state.mjs';
import { createDeliveryPump } from '../../scripts/chatto-delivery.mjs';

async function fixture(t, handler) {
  const server = createServer(async (req, res) => {
    let body = '';
    for await (const chunk of req) body += chunk;
    assert.equal(req.headers.authorization, 'Bearer test-token');
    assert.equal(req.headers['content-type'], 'application/json');
    await handler(req.url, JSON.parse(body), res);
  });
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => new Promise(resolve => {
    server.close(resolve);
    server.closeAllConnections();
  }));
  // Scale the former 15-minute cutoff down so the regression runs quickly.
  return createEveBridge({ baseUrl: `http://127.0.0.1:${server.address().port}`,
    token: 'test-token', timeoutMs: 100 });
}

test('submission returns before silent work finishes; a later request delivers its thread and attachments once', { timeout: 5000 }, async t => {
  const resources = [{ type: 'file', filename: 'part.step',
    content: 'data:application/octet-stream;base64,Y2Fk' }];
  let turns = 0, work, completed = false, delivered = false;
  const eve = await fixture(t, async (path, payload, res) => {
    if (path === '/api/chatto/conversations') {
      res.end(JSON.stringify({ conversation_id: 'conversation' }));
      return;
    }
    if (path === '/api/chatto/submit') {
      assert.equal(payload.conversation_id, 'conversation'); turns++;
      work = delay(350).then(() => { completed = true; });
      res.statusCode = 202;
      res.end(JSON.stringify({ id: 'chatto-job:message', state: 'queued' }));
    } else if (path === '/api/chatto/deliveries') {
      res.end(JSON.stringify({ deliveries: completed && !delivered ? [{ id: 'chatto-job:message',
        claim_token: 'claim', target: { room_id: 'dm', thread_root_id: 'message', conversation_id: 'branch' },
        payload: { notification: { message: 'Fertig' }, resources } }] : [] }));
    } else if (path === '/api/chatto/delivery-ack') {
      assert.equal(payload.status, 'delivered'); delivered = true; res.end('{}');
    } else { assert.equal(path, '/api/chatto/delivery-start'); res.end('{}'); }
  });
  const state = new ChattoState(':memory:');
  t.after(() => state.close());
  const replies = [];
  const ctx = { message: { id: 'message', authorId: 'owner', body: 'Auftrag', reasons: ['direct_message'] },
    transport: { room_kind: 'dm' }, conversationKey: 'dm', withTyping: work => work(),
    reply: async () => assert.fail('Direct reply') };
  await handleMessage(ctx, 'owner', state, eve);
  assert.equal(completed, false);
  await handleMessage(ctx, 'owner', state, eve);
  await work;
  const deliver = createDeliveryPump({ eve, signal: new AbortController().signal,
    send: async (delivery, dispatch) => { await dispatch(); replies.push(delivery); } });
  await deliver();
  await deliver();
  assert.equal(turns, 1);
  assert.equal(replies.length, 1);
  assert.equal(replies[0].payload.notification.message, 'Fertig');
  assert.deepEqual(replies[0].payload.resources, resources);
  assert.equal(replies[0].target.thread_root_id, 'message');
  assert.equal(replies[0].target.conversation_id, 'branch');
  assert.equal(state.db.prepare('SELECT status FROM deliveries').get().status, 'accepted');
});

test('ordinary bridge requests still time out when EVE stops responding', { timeout: 5000 }, async t => {
  const eve = await fixture(t, async () => {});
  await assert.rejects(eve('/api/chatto/conversations', {}), /EVE timeout/);
});

test('bot shutdown cancels a pending submission without repeating work', { timeout: 5000 }, async t => {
  const controller = new AbortController();
  let turns = 0;
  const eve = await fixture(t, async () => { turns++; controller.abort(); });
  const state = new ChattoState(':memory:');
  t.after(() => state.close());
  state.remember('dm', 'conversation');
  const ctx = { message: { id: 'message', authorId: 'owner', body: 'Auftrag', reasons: ['direct_message'] },
    transport: { room_kind: 'dm' }, conversationKey: 'dm', signal: controller.signal,
    withTyping: work => work(), reply: async () => assert.fail('Reply after cancellation') };
  await assert.rejects(handleMessage(ctx, 'owner', state, eve), { name: 'AbortError' });
  await handleMessage(ctx, 'owner', state, eve);
  assert.equal(turns, 1);
  assert.equal(state.db.prepare('SELECT status FROM deliveries').get().status, 'uncertain');
});

test('HTTP errors and broken connections fail without exposing the response or hanging', { timeout: 5000 }, async t => {
  const eve = await fixture(t, async (path, payload, res) => {
    if (payload.broken) { res.destroy(); return; }
    if (payload.invalid) { res.end('not JSON'); return; }
    res.statusCode = 403;
    res.end('private error details');
  });
  await assert.rejects(eve('/api/chatto/conversation', {}),
    { message: 'EVE API rejected request', code: 403 });
  await assert.rejects(eve('/api/chatto/conversation', { invalid: true }), /Invalid EVE response/);
  await assert.rejects(eve('/api/chatto/conversation', { broken: true }), { code: 'ECONNRESET' });
});
