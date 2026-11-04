import { test } from 'node:test';
import assert from 'node:assert/strict';
import { postScheduledAnswer, validateDestination } from '../../scripts/chatto-output.mjs';

function fixture() {
  const posts = [];
  const args = {
    config: { enabled: true, owner_user_id: 'owner', channel_ids: ['general'], channel_mentions_only: true },
    serverUrl: 'https://chat.example', viewerId: 'eve', ownerId: 'owner',
    target: { server_url: 'https://chat.example', room_id: 'general' },
    payload: { notification: { message: 'Neuigkeiten' }, resources: [] },
    userApi: { getUser: async () => ({ user: { user: { bot: { ownerUserId: 'owner' } } } }) },
    roomApi: { getRoom: async () => ({ room: { room: { id: 'general', kind: 1 }, viewerState: {
      isMember: true, permissions: ['message.read', 'message.post'].map(permission => ({ permission, granted: true })) } } }) },
    messageApi: { createMessage: async message => { posts.push(message); return { message: { id: 'sent' } }; },
      getMessage: async () => ({ message: { roomId: 'general', id: 'thread' } }) },
    uploadApi: {}, onDispatch: () => { args.dispatched = true; },
  };
  return { args, posts };
}

test('scheduled output posts without an incoming message, including exact thread destination', async () => {
  const { args, posts } = fixture();
  args.target.thread_root_id = 'thread';
  await postScheduledAnswer(args);
  assert.equal(posts[0].roomId, 'general');
  assert.equal(posts[0].threadRootEventId, 'thread');
  assert.equal(posts[0].inReplyTo, '');
  assert.equal(posts[0].body, 'Neuigkeiten');
  assert.equal(args.dispatched, true);
});

test('revoked room, changed server, missing permission and deleted thread fail before dispatch', async () => {
  for (const change of [
    a => { a.config.channel_ids = []; },
    a => { a.target.server_url = 'https://other.example'; },
    a => { a.config.enabled = false; },
    a => { a.roomApi.getRoom = async () => ({ room: { room: { id: 'general', kind: 1 }, viewerState: { isMember: true, permissions: [] } } }); },
    a => { a.target.thread_root_id = 'thread'; a.messageApi.getMessage = async () => ({ message: { deletedAt: 'now' } }); },
    a => { a.userApi.getUser = async () => ({ user: { user: { bot: { ownerUserId: 'other' } } } }); },
  ]) {
    const { args, posts } = fixture(); change(args);
    await assert.rejects(postScheduledAnswer(args));
    assert.equal(posts.length, 0);
    assert.equal(args.dispatched, undefined);
  }
});

test('a failed send is distinguishable from a validation failure', async () => {
  const { args } = fixture();
  args.messageApi.createMessage = async () => { throw new Error('connection lost'); };
  await assert.rejects(postScheduledAnswer(args));
  assert.equal(args.dispatched, true);
});

test('activity needs bot identity and readable membership/thread, without requiring post permission', async () => {
  const { args, posts } = fixture();
  args.target.thread_root_id = 'thread';
  args.readOnly = true;
  args.roomApi.getRoom = async () => ({ room: { room: { id: 'general', kind: 1 }, viewerState: {
    isMember: true, permissions: [{ permission: 'message.read', granted: true }] } } });
  await validateDestination(args);
  assert.equal(posts.length, 0);
  await assert.rejects(validateDestination({ ...args, readOnly: false }));
  for (const patch of [
    { userApi: { getUser: async () => ({ user: { user: {} } }) } },
    { roomApi: { getRoom: async () => ({ room: { room: { id: 'general', kind: 1 },
      viewerState: { isMember: false, permissions: [{ permission: 'message.read', granted: true }] } } }) } },
    { messageApi: { getMessage: async () => { throw Error('Thread not readable'); } } },
  ]) await assert.rejects(validateDestination({ ...args, ...patch }));
});

function personalFixture(recipient = 'owner') {
  const { args, posts } = fixture();
  args.target = { server_url: args.serverUrl, bot_id: 'eve', room_kind: 'dm',
    recipient_user_id: recipient, sender_id: recipient,
    access_profile: recipient === 'owner' ? 'owner_dm' : 'member_dm' };
  args.config.owner_dm_enabled = true;
  args.config.member_dm_enabled = true;
  args.userApi.getUser = async request => ({ user: { user: request.target.value === 'eve'
    ? { bot: { ownerUserId: 'owner' } } : { id: request.target.value } } });
  const room = { room: { id: 'personal', kind: 2 }, memberUserIds: ['eve', recipient],
    viewerState: { isMember: true, permissions: ['message.read', 'message.post'].map(permission => ({ permission, granted: true })) } };
  args.roomApi.listRooms = async () => ({ rooms: [room] });
  args.roomApi.getRoom = async () => ({ room });
  return { args, posts, room };
}

test('channel-requested reminder finds an existing DM without EVE history and sends a private root', async () => {
  for (const recipient of ['owner', 'member']) {
    const { args, posts, room } = personalFixture(recipient);
    const offsets = [];
    args.roomApi.listRooms = async request => {
      offsets.push(request.page.offset);
      return request.page.offset ? { rooms: [room] } : { rooms: [], page: { hasMore: true } };
    };
    await postScheduledAnswer(args);
    assert.deepEqual(offsets, [0, 100]);
    assert.equal(posts.length, 1);
    assert.equal(posts[0].roomId, 'personal');
    assert.equal(posts[0].threadRootEventId, '');
    assert.equal(posts[0].inReplyTo, '');
    assert.equal(args.target.room_id, undefined);
    assert.equal(args.dispatched, true);
  }
});

test('missing or unsafe personal DM never falls back to the channel or another recipient', async () => {
  for (const change of [
    a => { a.roomApi.listRooms = async () => ({ rooms: [] }); },
    a => { a.config.owner_dm_enabled = false; },
    a => { a.config.enabled = false; },
    a => { a.target.thread_root_id = 'channel-thread'; },
    a => { a.target.sender_id = 'someone-else'; },
    a => { a.target.bot_id = 'other-bot'; },
    a => { a.target.server_url = 'https://other.example'; },
    a => { a.userApi.getUser = async () => ({ user: { user: { deleted: true } } }); },
    (a, r) => { r.memberUserIds.push('third-user'); },
    (a, r) => { r.memberUserIds = ['eve', 'someone-else']; },
    (a, r) => { r.viewerState.permissions = []; },
    (a, r) => { r.room.archived = true; },
    (a, r) => { a.target.room_id = 'personal'; r.memberUserIds = ['eve', 'someone-else']; },
  ]) {
    const { args, posts, room } = personalFixture();
    change(args, room);
    await assert.rejects(postScheduledAnswer(args), error => error.permanent === true);
    assert.equal(posts.length, 0);
    assert.equal(args.dispatched, undefined);
  }
});

test('DM directory transport errors remain retryable before dispatch', async () => {
  const { args, posts } = personalFixture();
  args.roomApi.listRooms = async () => { throw new Error('offline'); };
  await assert.rejects(postScheduledAnswer(args), error => !error.permanent);
  assert.equal(posts.length, 0);
  assert.equal(args.dispatched, undefined);
});
