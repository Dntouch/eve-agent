const { test } = require('node:test');
const assert = require('node:assert/strict');
const zlib = require('node:zlib');
require('../../web/chat-export.js');
const { loadConversation, encodePng } = globalThis.EveChatExport;
function crc32(data) {
  let value = 0xffffffff;
  for (const byte of data) {
    value ^= byte;
    for (let bit = 0; bit < 8; bit++) value = (value & 1) ? (value >>> 1) ^ 0xedb88320 : value >>> 1;
  }
  return (value ^ 0xffffffff) >>> 0;
}

test('paginates past the visible history and includes failures only once', async () => {
  const calls = [];
  const result = await loadConversation(async before => {
    calls.push(before);
    return before === undefined
      ? { conversation: { id: 'active' }, messages: [{ id: 'two', ordinal: 2, created_at: '2026-10-20T12:02Z' }], failures: [{ created_at: '2026-10-20T12:01Z' }], has_more: true }
      : { messages: [{ id: 'one', ordinal: 1, created_at: '2026-10-20T12:00Z' }], failures: [{ created_at: '2026-10-20T12:01Z' }], has_more: false };
  });
  assert.deepEqual(calls, [undefined, 2]);
  assert.equal(result.timeline.length, 3);
  assert.equal(result.timeline[0].id, 'one');
  assert.ok(result.timeline[1].failure_report);
  assert.equal(result.timeline[2].id, 'two');
});

test('fails clearly when paging cannot make progress', async () => {
  await assert.rejects(loadConversation(async () => ({ messages: [{ id: 'one', ordinal: 1 }], has_more: true })), /vollständige/);
});

test('encodes a single PNG beyond canvas height limits with exact RGBA rows and valid checksums', async () => {
  const height = 40001;
  async function* tiles() {
    for (let start = 0; start < height; start += 2048) {
      const rows = Math.min(2048, height - start);
      const data = new Uint8Array(8 * rows);
      for (let row = 0; row < rows; row++) data.set([start % 256, row % 256, 200, 255, 1, 2, 3, 255], row * 8);
      yield { width: 2, height: rows, data };
    }
  }
  const blob = await encodePng(2, height, tiles());
  assert.equal(blob.type, 'image/png');
  const bytes = Buffer.from(await blob.arrayBuffer());
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const data = [];
  const types = [];
  for (let offset = 8; offset < bytes.length;) {
    const length = bytes.readUInt32BE(offset);
    const type = bytes.toString('ascii', offset + 4, offset + 8);
    const payload = bytes.subarray(offset + 8, offset + 8 + length);
    assert.equal(crc32(bytes.subarray(offset + 4, offset + 8 + length)), bytes.readUInt32BE(offset + 8 + length));
    types.push(type);
    if (type === 'IHDR') { assert.equal(payload.readUInt32BE(0), 2); assert.equal(payload.readUInt32BE(4), height); }
    if (type === 'IDAT') data.push(payload);
    offset += length + 12;
  }
  assert.equal(types.at(-1), 'IEND');
  const raw = zlib.inflateSync(Buffer.concat(data));
  assert.equal(raw.length, height * 9);
  assert.deepEqual([...raw.subarray(0, 9)], [0, 0, 0, 200, 255, 1, 2, 3, 255]);
  assert.equal(raw[(height - 1) * 9 + 4], 255);
});

test('does not produce a partial PNG after missing tiles or rendering errors', async () => {
  async function* missing() { yield { width: 1, height: 1, data: new Uint8Array(4) }; }
  await assert.rejects(encodePng(1, 2, missing()), /vollständig/);
  async function* broken() { throw new Error('render failed'); }
  await assert.rejects(encodePng(1, 1, broken()), /render failed/);
});
