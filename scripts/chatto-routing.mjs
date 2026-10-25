// Match protocol identities and configured permissions, never user wording.
export function selectRoute(config, viewerId, ownerId, room, message) {
  if (ownerId !== config.owner_user_id || message.authorId === viewerId
      || typeof message.body !== 'string' || message.body.length > 32000) return;
  const info = room.room;
  if (!info || !room.viewerState?.isMember || info.archived) return;
  if (info.kind === 2) {
    const members = room.memberUserIds || [];
    if (members.length !== 2 || !members.includes(message.authorId) || !members.includes(viewerId)) return;
    if (message.authorId === ownerId) {
      if (config.owner_dm_enabled) return { kind: 'dm', profile: 'owner_dm' };
    } else if (config.member_dm_enabled) return { kind: 'dm', profile: 'member_dm' };
    return;
  }
  if (info.kind === 1 && config.channel_ids.includes(info.id)) {
    if (config.channel_mentions_only && !message.reasons.includes('mention')) {
      if (config.channel_learning_ids?.includes(info.id)) return { kind: 'channel', profile: 'public_channel', observeOnly: true };
      return;
    }
    return { kind: 'channel', profile: 'public_channel' };
  }
}

export function scopeForRoute(serverUrl, viewerId, message, route) {
  const scope = [serverUrl, viewerId, message.roomId,
    route.kind === 'dm' ? message.authorId : 'public_channel'];
  if (message.threadRootId) scope.push(message.threadRootId);
  return JSON.stringify(scope);
}
