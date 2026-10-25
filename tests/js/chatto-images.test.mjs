import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadImages } from '../../scripts/chatto-images.mjs';
import { ChattoState, handleMessage } from '../../scripts/chatto-state.mjs';

test('downloads image assets only from their message room with explicit limits', async () => {
  const calls = [];
  const png = Buffer.from('89504e470d0a1a0a', 'hex');
  const server = { readAttachment: async (...args) => { calls.push(args); return { contentType: 'image/png', data: png }; } };
  const message = { roomId: 'room', attachments: [
    { id: 'photo', contentType: 'image/png' }, { id: 'document', contentType: 'application/pdf' },
  ] };
  assert.deepEqual(await loadImages(server, message), [`data:image/png;base64,${png.toString('base64')}`]);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0][0], { roomId: 'room', attachmentId: 'photo' });
  assert.equal(calls[0][1].maxImageSize, 2048);
  assert.equal(calls[0][1].maxBytes, 5 * 1024 * 1024);
  await assert.rejects(loadImages(server, { ...message, attachments: Array(5).fill(message.attachments[0]) }));
  await assert.rejects(loadImages({ readAttachment: async () => ({ contentType: 'text/html', data: png }) }, message));
});

test('image-only DM reaches EVE as images and failed downloads never trigger a text-only answer', async () => {
  const state = new ChattoState(':memory:');
  const image = 'data:image/png;base64,iVBORw0KGgo=';
  const message = { id: 'photo', authorId: 'owner', body: '', reasons: ['direct_message'], attachments: [{ id: 'a', contentType: 'image/png' }] };
  const requests = [];
  const ctx = { message, transport: { room_kind: 'dm' }, conversationKey: 'dm',
    loadImages: async () => [image], withTyping: fn => fn(), reply: async () => {} };
  const eve = async (path, payload) => {
    requests.push({ path, payload });
    return path.endsWith('conversations') ? { conversation_id: 'conversation' } : { answer: 'Bild gesehen' };
  };
  try {
    await handleMessage(ctx, 'owner', state, eve);
    assert.deepEqual(requests.at(-1).payload.images, [image]);
    assert.equal(requests.at(-1).payload.text, '');
    const failing = { ...ctx, message: { ...message, id: 'failed' }, loadImages: async () => { throw Error('no access'); } };
    await assert.rejects(handleMessage(failing, 'owner', state, eve));
    assert.equal(requests.length, 2);
  } finally { state.close(); }
});
