import { createHash } from 'node:crypto';

const TYPES = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp', 'image/gif': 'gif' };
const hash = bytes => createHash('sha256').update(bytes).digest('hex');

function imageFile(resource, index) {
  const match = /^data:(image\/(?:jpeg|png|webp|gif));base64,([A-Za-z0-9+/]*={0,2})$/.exec(resource.content || '');
  if (!match) throw new Error('Unsupported EVE image resource');
  const bytes = Buffer.from(match[2], 'base64');
  if (!bytes.length || bytes.length > 5 * 1024 * 1024 || bytes.toString('base64') !== match[2]) throw new Error('Invalid EVE image resource');
  return { bytes, contentType: match[1], filename: `eve-bild-${index + 1}.${TYPES[match[1]]}` };
}

export async function postAnswer(uploadApi, messageApi, destination, text, resources = [], signal) {
  const imageResources = resources.filter(r => r.type === 'image');
  if (imageResources.length > 4) throw new Error('Too many EVE output images');
  const files = imageResources.map(imageFile);
  const options = { signal, timeoutMs: 30000 };
  const assets = [];
  for (const file of files) {
    let uploadId;
    try {
      const created = await uploadApi.createUpload({
        roomId: destination.roomId, filename: file.filename, contentType: file.contentType,
        size: BigInt(file.bytes.length), sha256: hash(file.bytes),
      }, options);
      uploadId = created.upload?.uploadId;
      if (!uploadId) throw new Error('Chatto upload ID missing');
      const chunkSize = Math.max(1, Math.min(created.upload.maxChunkSize || 512 * 1024, 512 * 1024));
      for (let offset = 0; offset < file.bytes.length; offset += chunkSize) {
        const chunk = file.bytes.subarray(offset, offset + chunkSize);
        await uploadApi.uploadChunk({ uploadId, offset: BigInt(offset), content: chunk, chunkSha256: hash(chunk) }, options);
      }
      const completed = await uploadApi.completeUpload({ uploadId }, options);
      if (!completed.asset?.id) throw new Error('Chatto image asset missing');
      assets.push(completed.asset.id);
    } catch (error) {
      if (uploadId) await uploadApi.cancelUpload({ uploadId }, { timeoutMs: 3000 }).catch(() => {});
      throw error;
    }
  }
  const characters = Array.from(text);
  const ids = [];
  for (let offset = 0; offset < Math.max(1, characters.length); offset += 8000) {
    const response = await messageApi.createMessage({
      roomId: destination.roomId, body: characters.slice(offset, offset + 8000).join(''),
      threadRootEventId: destination.threadRootId || '', inReplyTo: destination.inReplyTo || '',
      attachmentAssetIds: offset === 0 ? assets : [],
    }, options);
    if (!response.message?.id) throw new Error('Chatto answer ID missing');
    ids.push(response.message.id);
  }
  return { ids };
}
