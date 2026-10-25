import { selectRoute } from './chatto-routing.mjs';
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

function outputFile(resource, index) {
  if (resource.type === 'image') return imageFile(resource, index);
  const match = /^data:([a-z0-9.+-]+\/[a-z0-9.+-]+);base64,([A-Za-z0-9+/]*={0,2})$/i.exec(resource.content || '');
  if (!match) throw new Error('Unsupported EVE file resource');
  const bytes = Buffer.from(match[2], 'base64');
  if (!bytes.length || bytes.length > 20 * 1024 * 1024 || bytes.toString('base64') !== match[2]) throw new Error('Invalid EVE file resource');
  const filename = String(resource.filename || `eve-datei-${index + 1}.bin`).split(/[\\/]/).pop();
  if (!filename || /[\x00-\x1f]/.test(filename)) throw new Error('Invalid EVE filename');
  return { bytes, contentType: match[1], filename };
}

export async function postAnswer(uploadApi, messageApi, destination, text, resources = [], signal) {
  const outputs = resources.filter(r => r.type === 'image' || r.type === 'file');
  if (outputs.filter(r => r.type === 'image').length > 4 || outputs.length > 8) throw new Error('Too many EVE output attachments');
  const files = outputs.map(outputFile);
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

// Validate the current destination independently of any triggering message.
export async function postScheduledAnswer({ config, serverUrl, viewerId, ownerId, target, payload,
  userApi, roomApi, messageApi, uploadApi, signal, onDispatch }) {
  if (!config.enabled || target.server_url !== serverUrl || (target.bot_id && target.bot_id !== viewerId)) throw new Error('Destination configuration changed');
  const options = { signal, timeoutMs: 10000 };
  const currentBot = await userApi.getUser({ target: { case: 'userId', value: viewerId } }, options);
  if (currentBot.user?.user?.bot?.ownerUserId !== config.owner_user_id) throw new Error('Bot ownership changed');
  const { room } = await roomApi.getRoom({ roomId: target.room_id }, options);
  if (!room) throw new Error('Destination unavailable');
  const probe = { body: '', authorId: target.sender_id || ownerId, roomId: target.room_id, reasons: ['mention'], threadRootId: target.thread_root_id };
  if (!selectRoute(config, viewerId, ownerId, room, probe)) throw new Error('Destination no longer enabled');
  const permissions = new Set((room.viewerState?.permissions || []).filter(p => p.granted).map(p => p.permission));
  if (!(permissions.has('message.read') || permissions.has('message.read-interactions')) ||
      !(target.thread_root_id ? ['message.post', 'message.post-in-thread', 'message.post-in-interactions'].some(p => permissions.has(p)) : permissions.has('message.post'))) throw new Error('Destination permissions missing');
  if (target.thread_root_id) {
    const root = await messageApi.getMessage({ roomId: target.room_id, eventId: target.thread_root_id }, options);
    if (!root.message || root.message.deletedAt || root.message.roomId !== target.room_id || root.message.id !== target.thread_root_id) throw new Error('Destination thread unavailable');
  }
  onDispatch();
  return postAnswer(uploadApi, messageApi, { roomId: target.room_id, threadRootId: target.thread_root_id || '' },
    payload.notification.message, payload.resources || [], signal);
}
