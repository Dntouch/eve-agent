import { readFileSync, mkdirSync, chmodSync, writeFileSync, renameSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { ChattoState, handleMessage, adoptRoomConversation } from './chatto-state.mjs';
import { selectRoute, scopeForRoute } from './chatto-routing.mjs';
import { loadImages } from './chatto-images.mjs';
import { createBotPresence } from './chatto-presence.mjs';
import { postQueuedAnswer, validateDestination } from './chatto-output.mjs';
import { createDeliveryPump } from './chatto-delivery.mjs';
import { createBotActivityReporter } from './chatto-activity.mjs';
import { createEveBridge } from './chatto-bridge.mjs';

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
const eve = createEveBridge({ baseUrl: eveBase, token: bridgeToken, ca });

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
let activity;
let roomRefreshTimer;
let deliveryTimer;
let progressTimer;
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
      readActivity: () => eve('/api/chatto/presence-activity', {},
        AbortSignal.any([controller.signal, AbortSignal.timeout(5000)])),
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
  function deliveryArgs(target, signal = controller.signal) {
    config = JSON.parse(readFileSync(effectivePath, 'utf8')).chatto;
    return { config, serverUrl, viewerId, ownerId, target,
      userApi: server.service(UserService), roomApi: server.service(RoomDirectoryService),
      messageApi: server.service(MessageService), uploadApi: server.service(AssetUploadService),
      signal };
  }
  activity = createBotActivityReporter({ serverUrl, botId: viewerId, apiKey: process.env.EVE_CHATTO_BOT_KEY,
    signal: controller.signal,
    validate: (target, signal) => validateDestination({ ...deliveryArgs(target), signal, readOnly: true }),
  });
  const deliver = createDeliveryPump({ eve, signal: controller.signal,
    isConnected: () => server.status === 'connected',
    send: async (delivery, onDispatch, signal) => {
      const target = delivery.target;
      if (target.conversation_id && target.thread_root_id) {
        const scope = scopeForRoute(serverUrl, viewerId, { roomId: target.room_id,
          authorId: target.sender_id, threadRootId: target.thread_root_id }, { kind: target.room_kind });
        const known = state.conversation(scope);
        if (known && known !== target.conversation_id) throw Object.assign(new Error('Thread binding conflict'), { permanent: true });
        if (!known) state.remember(scope, target.conversation_id);
      }
      await (presence ? presence.withWork(() => postQueuedAnswer({ ...deliveryArgs(target, signal), payload: delivery.payload, onDispatch }))
        : postQueuedAnswer({ ...deliveryArgs(target, signal), payload: delivery.payload, onDispatch }));
    },
    onDelivered: delivery => {
      if (delivery.id.startsWith('chatto-job:')) {
        state.finish(delivery.target.message_id, 'replied');
      }
    },
  });
  let checkingProgress = false;
  let activityRevision = 0;
  async function refreshProgress() {
    if (checkingProgress || controller.signal.aborted || server.status !== 'connected') return;
    checkingProgress = true;
    const generation = activityRevision;
    try {
      const batch = await eve('/api/chatto/jobs', {}, AbortSignal.any([controller.signal, AbortSignal.timeout(1500)]));
      if (generation === activityRevision && !controller.signal.aborted) activity.syncJobs(batch.jobs);
    } finally { checkingProgress = false; }
  }
  deliveryTimer = setInterval(() => deliver().catch(() => {
    console.warn(`${new Date().toISOString()} Chatto delivery polling failed; persisted delivery state retained.`);
  }), 3000);
  progressTimer = setInterval(() => refreshProgress().catch(() => {}), 500);
  void refreshProgress().catch(() => {});
  console.log('EVE bot connected. Configured DMs and channels enabled.');
  await server.consumeEvents({
    signal: controller.signal,
    onStatus: update => {
      activityRevision++;
      presence?.setConnected(update.state === 'ready');
      activity.setConnected(update.state === 'ready');
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
        await handleMessage({
          message, conversationKey: scope, transport: context, signal, observeOnly: Boolean(route.observeOnly),
          onAccepted: job => { activityRevision++; activity.acceptJob(job.id, context); },
          loadImages: () => loadImages(server, message, signal),
          withTyping: work => {
            const typing = () => activity.withWork(context, work, signal);
            return presence ? presence.withWork(typing) : typing();
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
} finally { clearInterval(progressTimer); clearInterval(deliveryTimer); clearInterval(roomRefreshTimer); await activity?.stop(); await presence?.stop(); client.close(); state.close(); status('stopped'); }
