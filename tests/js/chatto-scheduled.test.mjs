import { test } from 'node:test';
import assert from 'node:assert/strict';
import { postScheduledAnswer } from '../../scripts/chatto-output.mjs';

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
