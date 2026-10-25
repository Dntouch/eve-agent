import { readFileSync, mkdirSync, chmodSync, writeFileSync, renameSync } from 'node:fs';
import { request as httpsRequest } from 'node:https';
import { request as httpRequest } from 'node:http';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { ChattoState, handleMessage, adoptRoomConversation } from './chatto-state.mjs';
import { selectRoute, scopeForRoute } from './chatto-routing.mjs';
import { loadImages } from './chatto-images.mjs';
import { createBotPresence } from './chatto-presence.mjs';
import { postAnswer, postScheduledAnswer } from './chatto-output.mjs';
import { threadProgress } from './chatto-progress.mjs';

process.umask(0o077);
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const { createClient, UserService, RoomDirectoryService, MessageService, MyAccountService, AssetUploadService } = await import('../runtime/chatto/client.mjs');
const effectivePath = process.env.EVE_CHATTO_CONFIG || resolve(root, 'runtime/chatto/effective-config.json');
const effective = JSON.parse(readFileSync(effectivePath, 'utf8'));
let config = effective.chatto;
if (!config.enabled || !process.env.EVE_CHATTO_BOT_KEY) throw new Error('Chatto configuration or key missing');
const serverUrl = config.server_url;
if (new URL(serverUrl).protocol !== 'https:') throw new Error('Chatto requires HTTPS');
const directory = resolve(effective.paths.runtime, 'chatto');
const bridgeToken = readFileSync(resolve(directory, 'bridge-token'), 'utf8').trim();
const tls = Boolean(effective.visual.tls_cert && effective.visual.tls_key);
const ca = tls ? readFileSync(effective.visual.tls_cert) : undefined;
const eveBase = new URL(`${tls ? 'https' : 'http'}://127.0.0.1:${effective.visual.port || 8790}`);
const request = tls ? httpsRequest : httpRequest;
function eve(path, payload, signal) {
  return new Promise((ok, fail) => {
    const body = JSON.stringify(payload);
    const req = request(new URL(path, eveBase), {
      method: 'POST', ca, signal, timeout: 900000,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${bridgeToken}`,
        'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { text += chunk; if (text.length > 30 * 1024 * 1024) res.destroy(new Error('Response too large')); });
      res.on('error', fail);
      res.on('end', () => {
        if (res.statusCode < 200 || res.statusCode >= 300) return fail(Object.assign(new Error('EVE API rejected request'), { code: res.statusCode }));
        try { ok(JSON.parse(text)); } catch { fail(new Error('Invalid EVE response')); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('EVE timeout')));
    req.on('error', fail);
    req.end(body);
  });
}

mkdirSync(directory, { recursive: true, mode: 0o700 });
const state = new ChattoState(resolve(directory, 'state.sqlite'));
chmodSync(resolve(directory, 'state.sqlite'), 0o600);
const statusData = {};
function status(stateName, extra = {}) {
  const path = resolve(directory, 'status.json');
  writeFileSync(path + '.tmp', JSON.stringify({ state: stateName, updated_at: new Date().toISOString(), ...statusData, ...extra }));
  renameSync(path + '.tmp', path);
}
const client = createClient();
const server = client.connect({ serverUrl, apiKey: process.env.EVE_CHATTO_BOT_KEY });
const controller = new AbortController();
let presence;
let roomRefreshTimer;
let deliveryTimer;
for (const event of ['SIGINT', 'SIGTERM']) process.on(event, () => { controller.abort(); });
status('connecting');
try {
  const { viewerId } = await server.ready({ signal: controller.signal });
  const bot = await server.service(UserService).getUser({ target: { case: 'userId', value: viewerId } });
  const ownerId = bot.user?.user?.bot?.ownerUserId;
  if (!ownerId || ownerId !== config.owner_user_id) throw new Error('Bot ownership mismatch');
  if (config.presence_enabled !== false) {
    presence = createBotPresence(server.service(MyAccountService), {
      onError: () => console.error('Chatto presence update failed; automatic expiry remains active.'),
    });
    await presence.setConnected(true);
  }
  let refreshing = false;
  async function refreshRooms() {
    if (refreshing || controller.signal.aborted) return;
    refreshing = true;
    try {
      const rooms = [];
      for (let offset = 0; ; offset += 100) {
        const page = await server.service(RoomDirectoryService).listRooms({ page: { limit: 100, offset } }, { signal: controller.signal });
        rooms.push(...page.rooms.filter(r => r.room?.kind === 1).map(r => ({ id: r.room.id, name: r.room.name })));
        if (!page.page?.hasMore) break;
      }
      statusData.rooms = rooms;
      await eve('/api/chatto/output-rooms', { rooms }, controller.signal);
      const currentStatus = JSON.parse(readFileSync(resolve(directory, 'status.json'), 'utf8'));
      status(currentStatus.state);
    } finally { refreshing = false; }
  }
  await refreshRooms();
  roomRefreshTimer = setInterval(() => refreshRooms().catch(() => {}), 30000);
  let delivering = false;
  async function deliverScheduled() {
    if (delivering || controller.signal.aborted) return;
    delivering = true;
    try {
      const batch = await eve('/api/chatto/deliveries', {}, controller.signal);
      for (const delivery of batch.deliveries) {
        let dispatched = false;
        try {
          config = JSON.parse(readFileSync(effectivePath, 'utf8')).chatto;
          await postScheduledAnswer({
            config, serverUrl, viewerId, ownerId, target: delivery.target, payload: delivery.payload,
            userApi: server.service(UserService), roomApi: server.service(RoomDirectoryService),
            messageApi: server.service(MessageService), uploadApi: server.service(AssetUploadService),
            signal: controller.signal, onDispatch: () => { dispatched = true; },
          });
          await eve('/api/chatto/delivery-ack', { id: delivery.id, status: 'delivered' }, controller.signal);
        } catch {
          await eve('/api/chatto/delivery-ack', { id: delivery.id, status: dispatched ? 'uncertain' : 'blocked',
            error: dispatched ? 'Send outcome uncertain' : 'Destination validation failed' }, controller.signal);
        }
      }
    } finally { delivering = false; }
  }
  deliveryTimer = setInterval(() => deliverScheduled().catch(() => {}), 3000);
  console.log('EVE bot connected. Configured DMs and channels enabled.');
  await server.consumeEvents({
    signal: controller.signal,
    onStatus: update => {
      presence?.setConnected(update.state === 'ready');
      status(update.state, { gap: Boolean(update.gap) });
    },
    onEvent: async (event, { signal }) => {
      try {
        config = JSON.parse(readFileSync(effectivePath, 'utf8')).chatto;
        if (!config.enabled) return;
        if (event.event.case !== 'messagePosted' || !event.id || !event.actorId || event.actorId === viewerId) return;
        const posted = event.event.value;
        const message = {
          id: event.id, authorId: event.actorId, roomId: posted.roomId,
          body: posted.bodyPlaintext || '', threadRootId: posted.threadRootEventId || undefined,
          reasons: posted.mentions.some(mention => mention.includesViewer) ? ['mention'] : [],
        };
        const roomResponse = await server.service(RoomDirectoryService).getRoom({ roomId: message.roomId }, { signal });
        const room = roomResponse.room;
        if (!room) return;
        const route = selectRoute(config, viewerId, ownerId, room, message);
        if (!route) return;
        const currentBot = await server.service(UserService).getUser({ target: { case: 'userId', value: viewerId } }, { signal });
        if (currentBot.user?.user?.bot?.ownerUserId !== ownerId) throw new Error('Bot ownership changed');
        const author = await server.service(UserService).getUser({ target: { case: 'userId', value: message.authorId } }, { signal });
        if (!author.user?.user || author.user.user.bot || author.user.user.deleted) return;
        const permissions = new Set((room.viewerState?.permissions || []).filter(p => p.granted).map(p => p.permission));
        const canRead = permissions.has('message.read') || permissions.has('message.read-interactions');
        const canPost = config.reply_mode === 'chat' && !message.threadRootId ? permissions.has('message.post')
          : ['message.post', 'message.post-in-thread', 'message.post-in-interactions'].some(p => permissions.has(p));
        if (!canRead || (!route.observeOnly && !canPost)) { status('permissions_missing', { room_id: message.roomId, can_read: canRead, can_post: canPost }); return; }
        const currentMessage = await server.service(MessageService).getMessage({ roomId: message.roomId, eventId: message.id }, { signal });
        const readable = currentMessage.message;
        if (!readable || readable.id !== message.id || readable.roomId !== message.roomId
            || readable.actorId !== message.authorId || readable.deletedAt) return;
        message.body = readable.body || '';
        message.attachments = readable.attachments || [];
        message.threadRootId = readable.threadRootEventId || undefined;
        if (config.reply_mode === 'thread' && !route.observeOnly) message.threadRootId ||= message.id;
        const scope = scopeForRoute(serverUrl, viewerId, message, route);
        if (route.kind === 'dm' && !message.threadRootId) adoptRoomConversation(state, scope, serverUrl, viewerId, message);
        const context = {
          server_url: serverUrl, bot_id: viewerId, owner_id: ownerId,
          room_id: message.roomId, room_kind: route.kind, room_name: room.room.name || '',
          sender_id: message.authorId, sender_name: author.user.user.displayName || author.user.user.login,
          message_id: message.id,
          thread_root_id: message.threadRootId || "",
          access_profile: route.profile,
        };
        if (route.kind === 'dm') message.reasons.push('direct_message');
        const destination = { roomId: message.roomId, threadRootId: message.threadRootId || '' };
        await handleMessage({
          message, conversationKey: scope, transport: context, signal, observeOnly: Boolean(route.observeOnly),
          loadImages: () => loadImages(server, message, signal),
          withTyping: work => server.withTyping(destination, work, { signal }),
          progress: config.thread_status_enabled === false ? undefined : threadProgress(server.service(MessageService), destination, { signal, timeoutMs: 5000 }),
          bindThread: (root, id) => {
            const key = scopeForRoute(serverUrl, viewerId, { ...message, threadRootId: root }, route);
            const known = state.conversation(key);
            if (known && known !== id) throw new Error('Thread conversation binding conflict');
            if (!known) state.remember(key, id);
          },
          reply: async (text, resources, result) => {
            if (result?.thread_root_id) destination.threadRootId = result.thread_root_id;
            const latest = await server.service(RoomDirectoryService).getRoom({ roomId: message.roomId }, { signal });
            if (!latest.room || !selectRoute(config, viewerId, ownerId, latest.room, message)) throw new Error('Room access changed');
            const output = { ...destination,
              inReplyTo: destination.threadRootId ? message.id : '',
            };
            return postAnswer(server.service(AssetUploadService), server.service(MessageService), output, text, resources, signal);
          },
        }, ownerId, state, eve);
        status('ready');
      } catch (error) {
        if (signal.aborted) return;
        const code = typeof error.code === 'number' || /^[A-Z_]+$/.test(String(error.code || '')) ? error.code : null;
        status('turn_failed', { code });
        console.error('Chatto turn failed; no automatic action retry.');
      }
    },
  });
} catch {
  status('connection_failed');
  console.error('Chatto connection stopped or setup failed.');
  process.exitCode = controller.signal.aborted ? 0 : 1;
} finally { clearInterval(deliveryTimer); clearInterval(roomRefreshTimer); await presence?.stop(); client.close(); state.close(); status('stopped'); }
