import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { postAnswer } from '../../scripts/chatto-output.mjs';

test('actual image bytes are uploaded to the originating room and attached to the answer', async () => {
  const bytes = Buffer.from('ffd8ff112233445566778899', 'hex');
  const chunks = [];
  let uploaded, sent;
  const uploads = {
    createUpload: async payload => { uploaded = payload; return { upload: { uploadId: 'upload', maxChunkSize: 4 } }; },
    uploadChunk: async payload => { chunks.push(payload); return {}; },
    completeUpload: async () => ({ asset: { id: 'image-asset' } }),
  };
  const messages = { createMessage: async payload => { sent = payload; return { message: { id: 'answer' } }; } };
  const resources = [{ type: 'image', content: `data:image/jpeg;base64,${bytes.toString('base64')}` }];
  assert.deepEqual(await postAnswer(uploads, messages, { roomId: 'private-dm' }, 'Hier ist das Bild.', resources), { ids: ['answer'] });
  assert.equal(uploaded.roomId, 'private-dm');
  assert.equal(uploaded.sha256, createHash('sha256').update(bytes).digest('hex'));
  assert.deepEqual(Buffer.concat(chunks.map(c => c.content)), bytes);
  assert.deepEqual(chunks.map(c => c.offset), [0n, 4n, 8n]);
  assert.deepEqual(sent.attachmentAssetIds, ['image-asset']);
  assert.equal(sent.body, 'Hier ist das Bild.');
  assert.equal(sent.threadRootEventId, '');
  assert.equal(sent.roomId, 'private-dm');
});

test('upload failure cancels temporary upload and never posts a misleading text-only answer', async () => {
  let cancelled = false;
  let posts = 0;
  await assert.rejects(postAnswer({
    createUpload: async () => ({ upload: { uploadId: 'u', maxChunkSize: 3 } }),
    uploadChunk: async () => { throw Error('access denied'); },
    cancelUpload: async () => { cancelled = true; },
  }, { createMessage: async () => { posts++; } }, { roomId: 'r' }, 'Bild', [
    { type: 'image', content: 'data:image/jpeg;base64,/9j/AA==' },
  ]));
  assert.equal(cancelled, true);
  assert.equal(posts, 0);
});

test('text-only answers retain Unicode chunking and explicit thread destination', async () => {
  const requests = [];
  await postAnswer({}, { createMessage: async payload => { requests.push(payload); return { message: { id: String(requests.length) } }; } },
    { roomId: 'r', threadRootId: 'thread', inReplyTo: 'question' }, '🙂'.repeat(8001));
  assert.equal(requests.length, 2);
  assert.equal(Array.from(requests[0].body).length, 8000);
  assert.equal(requests[1].body, '🙂');
  assert.equal(requests[0].threadRootEventId, 'thread');
  assert.equal(requests[0].inReplyTo, 'question');
});
