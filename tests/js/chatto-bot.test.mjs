import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChattoState, handleMessage, permitted, roomScope, adoptRoomConversation, postInChat } from '../../scripts/chatto-state.mjs';

test('ordinary chat messages share context and answers target the room without a thread', async () => {
  const first = { ...message, roomId: 'dm' };
  const next = { ...first, id: 'm2', threadRootId: 'another-thread' };
  const scope = roomScope('https://chat.example', 'eve', first);
  assert.equal(scope, roomScope('https://chat.example', 'eve', next));
  assert.notEqual(scope, roomScope('https://other.example', 'eve', next));
  assert.notEqual(scope, roomScope('https://chat.example', 'eve', { ...next, roomId: 'other' }));
  let sent;
  await postInChat({ postMessage: async (...args) => { sent = args; } }, 'dm', 'Antwort');
  assert.deepEqual(sent[0], { roomId: 'dm', threadRootId: '' });
  assert.equal(sent[1], 'Antwort');
  const state = new ChattoState(':memory:');
  try {
    state.remember(JSON.stringify(['https://chat.example', JSON.stringify(['eve', 'dm', 'm1', 'owner'])]), 'previous');
    adoptRoomConversation(state, scope, 'https://chat.example', 'eve', first);
    assert.equal(state.conversation(scope), 'previous');
  } finally { state.close(); }
});

const message = { id: 'm1', authorId: 'owner', reasons: ['direct_message'], body: 'Hallo EVE' };
test('only owner text DMs are accepted', () => {
  assert.equal(permitted(message, 'owner'), true);
  for (const patch of [{ authorId: 'other' }, { reasons: ['mention'] }, { body: '' }, { body: 'x'.repeat(32001) }]) {
    assert.equal(permitted({ ...message, ...patch }, 'owner'), false);
  }
});
test('conversation survives restart and duplicate deliveries never re-execute actions', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'eve-chatto-'));
  let state = new ChattoState(join(dir, 'state.sqlite'));
  let turns = 0, creates = 0, replies = 0;
  const eve = async (path, payload) => {
    if (path === '/api/chatto/conversations') {
      assert.equal(payload.context.room_kind, 'dm');
      creates++; return { conversation_id: 'eve-1' };
    }
    turns++; assert.equal(payload.conversation_id, 'eve-1'); return { answer: 'Hallo!' };
  };
  const ctx = { message, transport: { room_kind: 'dm' }, conversationKey: 'thread1', withTyping: fn => fn(), reply: async () => { replies++; } };
  try {
    await handleMessage(ctx, 'owner', state, eve);
    state.close(); state = new ChattoState(join(dir, 'state.sqlite'));
    await handleMessage(ctx, 'owner', state, eve);
    await handleMessage({ ...ctx, message: { ...message, id: 'm2' } }, 'owner', state, eve);
    assert.deepEqual([creates, turns, replies], [1, 2, 2]);
    const broken = { ...ctx, message: { ...message, id: 'm3' }, reply: async () => { throw Error('uncertain send'); } };
    await assert.rejects(handleMessage(broken, 'owner', state, eve));
    await handleMessage(broken, 'owner', state, eve);
    assert.equal(turns, 3);
    assert.equal(state.db.prepare('SELECT status FROM deliveries WHERE id = ?').get('m3').status, 'uncertain');
  } finally { state.close(); rmSync(dir, { recursive: true }); }
});
test('silent observations never type, reply, fetch images or request an answer', async () => {
  const state = new ChattoState(':memory:');
  const calls = [];
  const unexpected = () => { throw new Error('Interactive work during observation'); };
  const ctx = { message: { ...message, reasons: [], body: 'Werkstattwissen' },
    transport: { room_kind: 'channel' }, conversationKey: 'general', observeOnly: true,
    withTyping: unexpected, reply: unexpected, loadImages: unexpected };
  try {
    const eve = async (path, payload) => {
      calls.push(path);
      if (path === '/api/chatto/conversations') return { conversation_id: 'c' };
      assert.equal(path, '/api/chatto/observe');
      assert.equal(payload.text, 'Werkstattwissen');
      return { status: 'observed' };
    };
    await handleMessage(ctx, 'owner', state, eve);
    await handleMessage(ctx, 'owner', state, eve);
    assert.deepEqual(calls, ['/api/chatto/conversations', '/api/chatto/observe']);
    assert.equal(state.db.prepare('SELECT status FROM deliveries').get().status, 'observed');
  } finally { state.close(); }
});
test('validated member DMs use the existing reply and image path', async () => {
  const state = new ChattoState(':memory:');
  let replied = 0;
  try {
    const ctx = { message: { ...message, authorId: 'member' },
      transport: { room_kind: 'dm', access_profile: 'member_dm' }, conversationKey: 'member-private',
      withTyping: fn => fn(), reply: async text => { assert.equal(text, 'Hallo'); replied++; } };
    await handleMessage(ctx, 'owner', state, async path =>
      path === '/api/chatto/conversations' ? { conversation_id: 'member-c' } : { answer: 'Hallo' });
    assert.equal(replied, 1);
  } finally { state.close(); }
});
