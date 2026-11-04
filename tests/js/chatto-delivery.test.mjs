import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createDeliveryPump } from '../../scripts/chatto-delivery.mjs';
import { postQueuedAnswer } from '../../scripts/chatto-output.mjs';

function fixture(send, { failAck = false, failStart = false } = {}) {
  const calls = [];
  const delivery = { id: 'chatto-job:one', claim_token: 'token', target: { room_id: 'room' },
    payload: { notification: { message: 'Fertig' } } };
  let pending = true, connected = true;
  const signal = new AbortController().signal;
  const eve = async (path, payload) => {
    calls.push([path, payload]);
    if (path.endsWith('/deliveries')) return { deliveries: pending ? [delivery] : [] };
    if (path.endsWith('/delivery-start')) {
      pending = false;
      if (failStart) throw Error('Start confirmation lost');
    }
    if (path.endsWith('/delivery-ack') && failAck) throw Error('Ack lost');
    if (path.endsWith('/delivery-ack') && payload.status === 'retry' && !pending) throw Error('Dispatch already started');
    return {};
  };
  const pump = () => createDeliveryPump({ eve, send, signal, isConnected: () => connected });
  return { calls, pump, disconnect: () => { connected = false; }, restoreBridge: () => { failAck = false; } };
}

test('validation/network failures before dispatch retry safely; permission failures stay blocked', async () => {
  for (const [error, expected] of [[Error('offline'), 'retry'],
    [Object.assign(Error('revoked'), { permanent: true }), 'blocked'],
    [Object.assign(Error('permission denied'), { code: 7 }), 'blocked']]) {
    const { calls, pump } = fixture(async () => { throw error; });
    await pump()();
    assert.equal(calls.at(-1)[1].status, expected);
    assert.equal(calls.some(([path]) => path.endsWith('/delivery-start')), false);
  }
});

test('dispatch is persisted before sending, and a possibly accepted send is never retried', async () => {
  let sends = 0;
  const f = fixture(async (delivery, dispatch) => {
    await dispatch();
    assert.equal(f.calls.at(-1)[0], '/api/chatto/delivery-start');
    sends++;
    throw Error('Connection lost after posting');
  });
  await f.pump()();
  assert.equal(f.calls.at(-1)[1].status, 'uncertain');
  await f.pump()(); // New pump represents a bot restart.
  assert.equal(sends, 1);
});

test('lost dispatch confirmation stops publication; a lost success ACK never resends', async () => {
  for (const options of [{ failStart: true }, { failAck: true }]) {
    let sends = 0;
    const f = fixture(async (delivery, dispatch) => { await dispatch(); sends++; }, options);
    await assert.rejects(f.pump()());
    await f.pump()();
    assert.equal(sends, options.failStart ? 0 : 1);
    assert.equal(f.calls.filter(([path]) => path.endsWith('/delivery-start')).length, 1);
  }
});

test('polls never overlap, and a disconnected bot does not claim output', async () => {
  let release, started;
  const waiting = new Promise(resolve => { release = resolve; });
  const entered = new Promise(resolve => { started = resolve; });
  const f = fixture(async (delivery, dispatch) => { started(); await waiting; await dispatch(); });
  const pump = f.pump();
  const first = pump();
  await entered;
  await pump();
  assert.equal(f.calls.filter(([path]) => path.endsWith('/deliveries')).length, 1);
  release(); await first;
  f.disconnect();
  await pump();
  assert.equal(f.calls.filter(([path]) => path.endsWith('/deliveries')).length, 1);
});

test('lost success acknowledgement retries only the ACK on the next poll', async () => {
  let sends = 0;
  const f = fixture(async (delivery, dispatch) => { await dispatch(); sends++; }, { failAck: true });
  const pump = f.pump();
  await assert.rejects(pump());
  f.restoreBridge();
  await pump();
  assert.equal(sends, 1);
  assert.deepEqual(f.calls.filter(([path]) => path.endsWith('/delivery-ack')).map(([, payload]) => payload.status),
    ['delivered', 'delivered']);
});

test('a lost dispatch-marker response never sends or queues an unsafe retry ACK', async () => {
  const f = fixture(async (delivery, dispatch) => { await dispatch(); assert.fail('Must not publish'); }, { failStart: true });
  await assert.rejects(f.pump()());
  assert.equal(f.calls.some(([path]) => path.endsWith('/delivery-ack')), false);
});

test('scheduled output follows the same persisted dispatch protocol as chat jobs', async () => {
  const order = [];
  const delivery = { id: 'scheduled-run', claim_token: 'schedule-token', target: {}, payload: {} };
  const pump = createDeliveryPump({ signal: new AbortController().signal,
    eve: async (path, payload) => {
      order.push(path);
      if (path.endsWith('/deliveries')) return { deliveries: [delivery] };
      assert.equal(payload.claim_token, 'schedule-token');
      return {};
    },
    send: async (item, dispatch, signal) => {
      assert.equal(signal.aborted, false);
      await dispatch(); order.push('posted');
    },
  });
  await pump();
  assert.deepEqual(order, ['/api/chatto/deliveries', '/api/chatto/delivery-start', 'posted', '/api/chatto/delivery-ack']);
});

test('delivery deadline releases a stalled pump with safe before/after-dispatch status', async () => {
  for (const dispatched of [false, true]) {
    const statuses = [];
    const pump = createDeliveryPump({ signal: new AbortController().signal, sendTimeoutMs: 5,
      eve: async (path, payload) => {
        if (path.endsWith('/deliveries')) return { deliveries: [{ id: 'scheduled', claim_token: 'token' }] };
        if (path.endsWith('/delivery-ack')) statuses.push(payload.status);
        return {};
      },
      send: async (delivery, dispatch, signal) => {
        if (dispatched) await dispatch();
        await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
      },
    });
    await Promise.all([pump(), new Promise(resolve => setTimeout(resolve, 20))]);
    assert.deepEqual(statuses, [dispatched ? 'uncertain' : 'retry']);
  }
});

test('uploads finish before the dispatch marker; a lost marker cannot post an attachment', async () => {
  const order = [];
  const args = {
    config: { enabled: true, owner_user_id: 'owner', owner_dm_enabled: true, channel_ids: [] },
    serverUrl: 'https://chat.example', viewerId: 'eve', ownerId: 'owner',
    target: { server_url: 'https://chat.example', bot_id: 'eve', room_id: 'dm', room_kind: 'dm',
      sender_id: 'owner', access_profile: 'owner_dm', thread_root_id: 'root', message_id: 'message' },
    payload: { notification: { message: 'Fertig' }, resources: [{ type: 'file', filename: 'part.step',
      content: 'data:application/octet-stream;base64,Y2Fk' }] },
    userApi: { getUser: async request => ({ user: { user: request.target.value === 'eve' ? { bot: { ownerUserId: 'owner' } } : {} } }) },
    roomApi: { getRoom: async () => ({ room: { room: { id: 'dm', kind: 2 }, memberUserIds: ['eve', 'owner'],
      viewerState: { isMember: true, permissions: ['message.read', 'message.post'].map(permission => ({ permission, granted: true })) } } }) },
    uploadApi: { createUpload: async () => ({ upload: { uploadId: 'upload' } }), uploadChunk: async () => {},
      completeUpload: async () => { order.push('uploaded'); return { asset: { id: 'asset' } }; } },
    messageApi: { getMessage: async () => ({ message: { roomId: 'dm', id: 'root' } }),
      createMessage: async message => { order.push('posted'); assert.equal(message.inReplyTo, 'message');
        assert.deepEqual(message.attachmentAssetIds, ['asset']); return { message: { id: 'reply' } }; } },
    onDispatch: async () => { order.push('dispatch'); },
  };
  await postQueuedAnswer(args);
  assert.deepEqual(order, ['uploaded', 'dispatch', 'posted']);
  order.length = 0;
  await assert.rejects(postQueuedAnswer({ ...args, onDispatch: async () => { throw Error('lost confirmation'); } }));
  assert.deepEqual(order, ['uploaded']);
  args.target.sender_id = 'other';
  await assert.rejects(postQueuedAnswer(args), { permanent: true });
});
