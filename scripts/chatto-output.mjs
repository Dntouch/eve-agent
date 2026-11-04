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

export async function postAnswer(uploadApi, messageApi, destination, text, resources = [], signal, onDispatch = () => {}) {
  const outputs = resources.filter(r => ['image', 'file', 'attachment'].includes(r.type));
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
      if (!completed.asset?.id) throw new Error('Chatto attachment asset missing');
      assets.push(completed.asset.id);
    } catch (error) {
      if (uploadId) await uploadApi.cancelUpload({ uploadId }, { timeoutMs: 3000 }).catch(() => {});
      throw error;
    }
  }
  const characters = Array.from(text);
  const ids = [];
  // Uploads alone cannot publish an answer. Persist dispatch immediately before
  // the first visible message; a lost acknowledgement must never replay it.
  await onDispatch();
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
export async function validateDestination({ config, serverUrl, viewerId, ownerId, target,
  userApi, roomApi, messageApi, signal, readOnly = false }) {
  const invalid = message => { throw Object.assign(new Error(message), { permanent: true }); };
  if (!config.enabled || target.server_url !== serverUrl || (target.bot_id && target.bot_id !== viewerId)) invalid('Destination configuration changed');
  const options = { signal, timeoutMs: 10000 };
  const currentBot = await userApi.getUser({ target: { case: 'userId', value: viewerId } }, options);
  if (currentBot.user?.user?.bot?.ownerUserId !== config.owner_user_id) invalid('Bot ownership changed');
  const { room } = await roomApi.getRoom({ roomId: target.room_id }, options);
  if (!room || room.room?.id !== target.room_id) invalid('Destination unavailable');
  if (target.recipient_user_id && (room.room.kind !== 2 || target.sender_id !== target.recipient_user_id ||
      room.memberUserIds?.length !== 2 || !room.memberUserIds.includes(target.recipient_user_id) ||
      !room.memberUserIds.includes(viewerId))) invalid('Personal DM recipient mismatch');
  const probe = { body: '', authorId: target.sender_id || ownerId, roomId: target.room_id, reasons: ['mention'], threadRootId: target.thread_root_id };
  const route = selectRoute(config, viewerId, ownerId, room, probe);
  if (!route || (target.access_profile && route.profile !== target.access_profile)) invalid('Destination no longer enabled');
  const permissions = new Set((room.viewerState?.permissions || []).filter(p => p.granted).map(p => p.permission));
  if (!(permissions.has('message.read') || permissions.has('message.read-interactions')) ||
      (!readOnly && !(target.thread_root_id ? ['message.post', 'message.post-in-thread', 'message.post-in-interactions'].some(p => permissions.has(p)) : permissions.has('message.post')))) invalid('Destination permissions missing');
  if (target.thread_root_id) {
    const root = await messageApi.getMessage({ roomId: target.room_id, eventId: target.thread_root_id }, options);
    if (!root.message || root.message.deletedAt || root.message.roomId !== target.room_id || root.message.id !== target.thread_root_id) invalid('Destination thread unavailable');
  }
  if (target.message_id || target.recipient_user_id) {
    const author = await userApi.getUser({ target: { case: 'userId', value: target.sender_id } }, options);
    if (!author.user?.user || author.user.user.bot || author.user.user.deleted) invalid('Origin sender unavailable');
  }
}

// Bots cannot call StartDM, including to fetch an existing DM. Resolve only an
// existing two-person room through the bot's authenticated room directory.
export async function resolvePersonalDM(args) {
  const { config, serverUrl, viewerId, ownerId, target, roomApi, userApi, signal } = args;
  if (!target.recipient_user_id) return target;
  const invalid = message => { throw Object.assign(new Error(message), { permanent: true }); };
  const recipient = target.recipient_user_id;
  const owner = recipient === ownerId;
  if (!config.enabled || target.server_url !== serverUrl || target.bot_id !== viewerId ||
      ownerId !== config.owner_user_id || target.room_kind !== 'dm' || target.sender_id !== recipient ||
      recipient === viewerId || target.thread_root_id || target.message_id ||
      target.access_profile !== (owner ? 'owner_dm' : 'member_dm') ||
      !config[owner ? 'owner_dm_enabled' : 'member_dm_enabled']) invalid('Personal DM is not enabled');
  const options = { signal, timeoutMs: 10000 };
  const author = await userApi.getUser({ target: { case: 'userId', value: recipient } }, options);
  if (!author.user?.user || author.user.user.bot || author.user.user.deleted) invalid('DM recipient unavailable');
  if (target.room_id) return target;
  for (let offset = 0; ; offset += 100) {
    const page = await roomApi.listRooms({ page: { limit: 100, offset } }, options);
    const room = page.rooms.find(r => r.room?.kind === 2 && !r.room.archived && r.viewerState?.isMember &&
      r.memberUserIds?.length === 2 && r.memberUserIds.includes(viewerId) && r.memberUserIds.includes(recipient));
    if (room) return { ...target, room_id: room.room.id };
    if (!page.page?.hasMore) break;
  }
  invalid('Open a personal DM with EVE once before requesting DM reminders; Chatto forbids bots from starting DMs');
}

export async function postQueuedAnswer(args) {
  args = { ...args, target: await resolvePersonalDM(args) };
  await validateDestination(args);
  const { target, payload, uploadApi, messageApi, signal, onDispatch } = args;
  return postAnswer(uploadApi, messageApi, { roomId: target.room_id, threadRootId: target.thread_root_id || '',
    inReplyTo: target.thread_root_id ? target.message_id || '' : '' },
    payload.notification.message, payload.resources || [], signal, onDispatch);
}

export const postScheduledAnswer = postQueuedAnswer;
