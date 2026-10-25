import { withProgress } from './chatto-progress.mjs';
import { DatabaseSync } from 'node:sqlite';

export class ChattoState {
  constructor(path) {
    this.db = new DatabaseSync(path);
    this.db.exec(`CREATE TABLE IF NOT EXISTS conversations (scope TEXT PRIMARY KEY, id TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, status TEXT NOT NULL);`);
  }
  claim(id) {
    return this.db.prepare("INSERT OR IGNORE INTO deliveries VALUES (?, 'started')").run(id).changes === 1;
  }
  finish(id, status) {
    this.db.prepare('UPDATE deliveries SET status = ? WHERE id = ?').run(status, id);
  }
  conversation(scope) {
    return this.db.prepare('SELECT id FROM conversations WHERE scope = ?').get(scope)?.id;
  }
  remember(scope, id) {
    this.db.prepare('INSERT INTO conversations VALUES (?, ?)').run(scope, id);
  }
  close() { this.db.close(); }
}

export function permitted(message, ownerId, memberDM = false) {
  return (message.authorId === ownerId || memberDM) && message.reasons.includes('direct_message')
    && typeof message.body === 'string' && (message.body.trim().length > 0
      || Boolean(message.attachments?.some(a => a.contentType?.startsWith('image/'))))
    && message.body.length <= 32000;
}

export function roomScope(serverUrl, viewerId, message) {
  return JSON.stringify([serverUrl, viewerId, message.roomId, message.authorId]);
}

export async function postInChat(server, roomId, text, signal) {
  // Empty threadRootId creates ordinary room messages, including split long answers.
  return server.postMessage({ roomId, threadRootId: '' }, text, { signal });
}

export function adoptRoomConversation(state, scope, serverUrl, viewerId, message) {
  if (state.conversation(scope)) return;
  for (const row of state.db.prepare('SELECT scope, id FROM conversations ORDER BY rowid DESC').all()) {
    try {
      const [origin, legacy] = JSON.parse(row.scope);
      if (origin !== serverUrl || typeof legacy !== 'string') continue;
      const [bot, room, , sender] = JSON.parse(legacy);
      if (bot === viewerId && room === message.roomId && sender === message.authorId) {
        state.remember(scope, row.id);
        return;
      }
    } catch { /* Unrelated conversation scope. */ }
  }
}

export async function handleMessage(ctx, ownerId, state, eve) {
  const message = ctx.message;
  if (!ctx.transport || (ctx.transport.room_kind !== 'channel'
      && !permitted(message, ownerId, ctx.transport.access_profile === 'member_dm'))) return;
  if (!state.claim(message.id)) return;
  try {
    const processMessage = async () => {
      const images = !ctx.observeOnly && ctx.loadImages ? await ctx.loadImages() : [];
      if (!message.body.trim() && !images.length) { state.finish(message.id, 'skipped'); return; }
      // Include server/account/room/sender; retain context across new chat messages.
      const scope = ctx.conversationKey;
      let id = state.conversation(scope);
      if (!id) {
        id = (await eve('/api/chatto/conversations', { context: ctx.transport }, ctx.signal)).conversation_id;
        if (typeof id !== 'string' || !id) throw new Error('Invalid conversation ID');
        state.remember(scope, id);
      }
      if (ctx.observeOnly) {
        await eve('/api/chatto/observe', {
          conversation_id: id, text: message.body, context: ctx.transport,
        }, ctx.signal);
        state.finish(message.id, 'observed');
        return;
      }
      const result = await eve('/api/chatto/conversation', {
        conversation_id: id, text: message.body, images, context: ctx.transport,
      }, ctx.signal);
      if (typeof result.answer !== 'string' || !result.answer.trim()) throw new Error('Empty EVE answer');
      if (result.thread_root_id && ctx.bindThread) ctx.bindThread(result.thread_root_id, result.conversation_id);
      await ctx.reply(result.answer, result.resources || [], result);
      state.finish(message.id, 'replied');
    };
    if (ctx.observeOnly) await processMessage();
    else await ctx.withTyping(() => ctx.progress ? withProgress(processMessage,
      () => eve('/api/chatto/activity', { conversation_id: state.conversation(ctx.conversationKey), context: ctx.transport },
        AbortSignal.any([ctx.signal || new AbortController().signal, AbortSignal.timeout(5000)])), ctx.progress)
      : processMessage());
  } catch (error) {
    // No automatic retry: EVE may already have performed an action or Chatto accepted a reply.
    state.finish(message.id, 'uncertain');
    throw error;
  }
}
