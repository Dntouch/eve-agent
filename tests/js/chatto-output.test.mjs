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

test('CAD files are uploaded as bytes with their filename into the same thread', async () => {
  let created, posted;
  const bytes = Buffer.from('ISO-10303-21;');
  await postAnswer({
    createUpload: async payload => { created = payload; return { upload: { uploadId: 'u', maxChunkSize: 100 } }; },
    uploadChunk: async payload => { assert.deepEqual(payload.content, bytes); },
    completeUpload: async () => ({ asset: { id: 'cad' } }),
  }, { createMessage: async payload => { posted = payload; return { message: { id: 'answer' } }; } },
  { roomId: 'room', threadRootId: 'root', inReplyTo: 'request' }, 'Fertig',
  [{ type: 'file', filename: 'halter.step', content: `data:application/octet-stream;base64,${bytes.toString('base64')}` }]);
  assert.equal(created.filename, 'halter.step');
  assert.equal(created.roomId, 'room');
  assert.equal(posted.threadRootEventId, 'root');
  assert.deepEqual(posted.attachmentAssetIds, ['cad']);
});
test('file paths and URLs never become uploaded attachments', async () => {
  for (const content of ['/private/file.step', 'https://example.org/model.step', 'data:application/octet-stream;base64,!!']) {
    await assert.rejects(postAnswer({}, {}, { roomId: 'room' }, 'Datei', [{ type: 'file', content }]));
  }
});
