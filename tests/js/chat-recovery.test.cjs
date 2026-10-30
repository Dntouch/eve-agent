const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../web/app.js'), 'utf8');
const recovery = source.slice(source.indexOf('  let backendReconnectTimer ='), source.indexOf('  elements.messageQueue.addEventListener'));

function client(events, status = 200) {
  const storage = new Map([['eve.activeBackendTurn', 'turn-1']]);
  const timers = [];
  const calls = [];
  let index = 0;
  const node = { classList: { add() {}, remove() {} }, remove() {}, querySelector() { return {}; } };
  const context = {
    TextDecoder, Uint8Array, requestBusy: false, activeConversationId: 'chat-a',
    activeBackendTurnId: null, backendTurnCancellable: false, latestVisibleTurnId: null,
    queuedMessages: [], auth: {}, elements: { turnCancel: {}, },
    window: { localStorage: { getItem: k => storage.get(k), setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) },
      setTimeout: (fn, delay) => { timers.push({fn, delay}); return timers.length; }, clearTimeout() {} },
    fetchWithTimeout: async url => {
      calls.push(url);
      return { ok: status === 200, status, body: { getReader: () => ({ read: async () => {
        if (index >= events.length) return { done: true };
        const event = events[index++];
        if (event instanceof Error) throw event;
        return { value: new TextEncoder().encode(JSON.stringify(event) + '\n'), done: false };
      } }) } };
    },
    selectConversation: async () => calls.push('history'),
    loadConversations: async () => calls.push('completed-history'),
    appendChatMessage: () => node, liveReasoningState: () => ({}),
    recoverStoredAnswer: async () => calls.push('recover'),
    streamFailure: e => Object.assign(new Error(e.error), { backendTerminal: true }),
  };
  for (const name of ['updatePTT','showState','setDetail','finishLiveReasoning','renderAssistantMarkdown','setReply','startAvatarCloudActivity','updateComposerActivity','finishAvatarCloudActivity','attachReasoningLink','ensureBackendUserMessage','appendLiveReasoning','cancelTurnAudio','renderArtifacts','renderSources','showTurnFailure','renderMessageQueue']) {
    context[name] = (...args) => { calls.push([name, ...args]); return Promise.resolve(); };
  }
  context.followTurnCompletion = async () => {};
  vm.createContext(context);
  vm.runInContext(recovery, context);
  return { context, storage, timers, calls };
}

test('reload reattaches with GET and restores the final answer', async () => {
  const c = client([{type:'accepted', cancellable:true}, {type:'status',status:'running',cancellable:true}, {type:'delta',content:'Fertig'}, {type:'complete',result:{answer:'Fertig',conversation_id:'chat-a'}}]);
  await c.context.resumeBackendTurn();
  assert.ok(c.calls.includes('/api/message/stream/turn-1'));
  assert.ok(c.calls.includes('completed-history'));
  assert.equal(c.storage.size, 0);
  assert.equal(c.context.requestBusy, false);
});

test('dropped stream keeps turn identity and schedules read-only reconnect', async () => {
  const c = client([{type:'accepted'}, new Error('network disconnected')]);
  await c.context.resumeBackendTurn();
  assert.equal(c.storage.get('eve.activeBackendTurn'), 'turn-1');
  assert.ok(c.timers.some(t => t.delay === 1000));
  assert.ok(!c.calls.some(call => Array.isArray(call) && call[0] === 'showTurnFailure'));
});

test('temporary HTTP failure retries but missing turn terminates recovery', async () => {
  for (const status of [503, 404]) {
    const c = client([], status);
    await c.context.resumeBackendTurn();
    assert.equal(c.storage.has('eve.activeBackendTurn'), status === 503);
    assert.equal(c.timers.length > 0, status === 503);
  }
});

test('backend failure and cancellation clear the pending marker', async () => {
  for (const event of [{type:'error',error:'tool failed'}, {type:'cancelled'}]) {
    const c = client([{type:'accepted'}, event]);
    await c.context.resumeBackendTurn();
    assert.equal(c.storage.size, 0);
    assert.equal(c.timers.length, 0);
    if (event.type === 'cancelled') assert.ok(c.calls.includes('completed-history'));
  }
});

test('existing observer prevents another attachment', async () => {
  const c = client([]);
  c.context.requestBusy = true;
  await c.context.resumeBackendTurn();
  assert.equal(c.calls.length, 0);
});
