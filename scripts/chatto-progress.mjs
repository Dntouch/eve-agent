// Poll request-bound EVE activity. Status delivery is best effort and never retries work.
export async function withProgress(work, read, publish, { intervalMs = 1500 } = {}) {
  let stopped = false, timer, pending;
  let latest;
  const tick = async () => {
    try {
      const activity = await read();
      if (!stopped && activity.state !== 'unknown') {
        latest = activity;
        await publish(activity.state === 'completed' ? { ...activity, state: 'working' } : activity);
      }
    } catch { /* Optional status must not interrupt the actual request. */ }
    if (!stopped) timer = setTimeout(() => { pending = tick(); }, intervalMs);
  };
  pending = tick();
  let failed = false;
  try { return await work(); }
  catch (error) { failed = true; throw error; }
  finally {
    stopped = true;
    clearTimeout(timer);
    await pending;
    if (latest) await publish({ ...latest, state: failed ? 'failed' : 'completed' }).catch(() => {});
  }
}

// One visible message per request, updated when the request ends.
export function threadProgress(messageApi, destination, options = {}) {
  let id, lastText;
  return async activity => {
    if (!activity.thread_root_id) return;
    destination.threadRootId = activity.thread_root_id;
    const text = activity.state === 'failed'
      ? 'EVE konnte den Auftrag nicht abschließen. Der Ausführungsstand muss geprüft werden.'
      : activity.state === 'completed' ? 'EVE hat die Bearbeitung beendet.'
        : activity.integration ? `EVE arbeitet mit ${activity.integration} …` : 'EVE arbeitet …';
    if (text === lastText) return;
    if (!id) {
      if (activity.state !== 'working') return;
      const result = await messageApi.createMessage({ roomId: destination.roomId,
        threadRootEventId: destination.threadRootId, body: text }, options);
      if (!result.message?.id) throw new Error('Chatto status message ID missing');
      id = result.message.id;
    } else {
      try {
        await messageApi.updateMessage({ roomId: destination.roomId, eventId: id, body: text,
          updateMask: { paths: ['body'] } }, options);
      } catch (error) {
        // An expired edit window must not leave only a stale "working" status.
        if (activity.state === 'working') throw error;
        await messageApi.createMessage({ roomId: destination.roomId,
          threadRootEventId: destination.threadRootId, body: text }, options);
      }
    }
    lastText = text;
  };
}
