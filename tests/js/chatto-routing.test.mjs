import { test } from 'node:test';
import assert from 'node:assert/strict';
import { selectRoute, scopeForRoute } from '../../scripts/chatto-routing.mjs';

const config = { owner_user_id: 'owner', owner_dm_enabled: true, channel_ids: ['general'], channel_mentions_only: true };
const room = { room: { id: 'general', kind: 1 }, viewerState: { isMember: true } };
const message = { id: 'm', roomId: 'general', authorId: 'member', body: 'Schalte das Licht an', reasons: ['mention'] };
test('channel routing depends on IDs, membership and mention metadata, never message wording', () => {
  assert.equal(selectRoute(config, 'eve', 'owner', room, message).profile, 'public_channel');
  for (const altered of [{ ...room, room: { ...room.room, id: 'other' } }, { ...room, viewerState: { isMember: false } }]) {
    assert.equal(selectRoute(config, 'eve', 'owner', altered, message), undefined);
  }
  assert.equal(selectRoute(config, 'eve', 'owner', room, { ...message, reasons: [] }), undefined);
  assert.equal(selectRoute(config, 'eve', 'owner', room, { ...message, authorId: 'eve' }), undefined);
  assert.equal(selectRoute(config, 'eve', 'new-owner', room, message), undefined);
  assert.ok(selectRoute({ ...config, channel_mentions_only: false }, 'eve', 'owner', room, { ...message, reasons: [] }));
});
test('DM privileges require the configured owner and exactly two participants', () => {
  const dm = { room: { id: 'dm', kind: 2 }, viewerState: { isMember: true }, memberUserIds: ['eve', 'owner'] };
  const request = { ...message, roomId: 'dm', authorId: 'owner' };
  assert.equal(selectRoute(config, 'eve', 'owner', dm, request).profile, 'owner_dm');
  assert.equal(selectRoute(config, 'eve', 'owner', dm, { ...request, authorId: 'other' }), undefined);
  assert.equal(selectRoute(config, 'eve', 'owner', { ...dm, memberUserIds: ['eve', 'owner', 'other'] }, request), undefined);
});
test('channel participants share conversation context; owner DM remains separate', () => {
  const route = { kind: 'channel' };
  assert.equal(scopeForRoute('server', 'eve', message, route), scopeForRoute('server', 'eve', { ...message, authorId: 'other', id: 'next' }, route));
  assert.notEqual(scopeForRoute('server', 'eve', message, route), scopeForRoute('server', 'eve', message, { kind: 'dm' }));
});
test('silent learning requires both room access and a separately selected learning channel', () => {
  const selected = { ...config, channel_learning_ids: ['general'] };
  const unmentioned = { ...message, reasons: [] };
  assert.equal(selectRoute(selected, 'eve', 'owner', room, unmentioned).observeOnly, true);
  assert.equal(selectRoute(selected, 'eve', 'owner', room, message).observeOnly, undefined);
  assert.equal(selectRoute({ ...selected, channel_ids: [] }, 'eve', 'owner', room, unmentioned), undefined);
  assert.equal(selectRoute({ ...selected, channel_learning_ids: [] }, 'eve', 'owner', room, unmentioned), undefined);
});
test('other members can use restricted two-person DMs when explicitly enabled', () => {
  const enabled = { ...config, member_dm_enabled: true };
  const dm = { room: { id: 'private', kind: 2 }, viewerState: { isMember: true }, memberUserIds: ['eve', 'member'] };
  const request = { ...message, roomId: 'private', reasons: [] };
  assert.equal(selectRoute(config, 'eve', 'owner', dm, request), undefined);
  assert.equal(selectRoute(enabled, 'eve', 'owner', dm, request).profile, 'member_dm');
  for (const memberUserIds of [['eve', 'member', 'third'], ['eve', 'different'], ['member', 'third']]) {
    assert.equal(selectRoute(enabled, 'eve', 'owner', { ...dm, memberUserIds }, request), undefined);
  }
  assert.equal(selectRoute(enabled, 'eve', 'owner', { ...dm, viewerState: { isMember: false } }, request), undefined);
  const ownerDM = { ...dm, memberUserIds: ['eve', 'owner'] };
  assert.equal(selectRoute(enabled, 'eve', 'owner', ownerDM, { ...request, authorId: 'owner' }).profile, 'owner_dm');
  assert.equal(selectRoute({ ...enabled, owner_dm_enabled: false }, 'eve', 'owner', ownerDM, { ...request, authorId: 'owner' }), undefined);
});

test('different threads separate context and replies in one thread keep context', () => {
  const route = { kind: 'channel' };
  const first = { ...message, threadRootId: 'root-one' };
  assert.equal(scopeForRoute('s', 'eve', first, route), scopeForRoute('s', 'eve', { ...first, id: 'reply', authorId: 'other' }, route));
  assert.notEqual(scopeForRoute('s', 'eve', first, route), scopeForRoute('s', 'eve', { ...first, threadRootId: 'root-two' }, route));
  assert.notEqual(scopeForRoute('s', 'eve', first, route), scopeForRoute('s', 'eve', message, route));
});
