// Presence is connection liveness; no interpretation of conversations or prompts.
export function createBotPresence(api, { schedule = setInterval, cancel = clearInterval, onError = () => {} } = {}) {
  let connected = false;
  let stopped = false;
  let timer;
  let tail = Promise.resolve();
  let initialized = false;
  const options = { timeoutMs: 3000 };
  function enqueue(work) {
    tail = tail.then(work).catch(() => onError());
    return tail;
  }
  async function choose(status) {
    const { preference } = await api.getPresencePreference({}, options);
    if (preference?.status !== status) {
      await api.setPresencePreference({ status, expectedRevision: preference?.revision || '' }, options);
    }
  }
  function tick() {
    return enqueue(async () => {
      if (!connected || stopped) return;
      // Preferences are initialized deliberately, never rewritten by heartbeats.
      if (!initialized) { await choose(1); initialized = true; }
      await api.refreshPresence({}, options);
    });
  }
  return {
    setConnected(value) {
      if (stopped || connected === value) return tail;
      connected = value;
      if (timer) { cancel(timer); timer = undefined; }
      if (!value) return tail;
      initialized = false;
      timer = schedule(tick, 30000);
      return tick();
    },
    stop() {
      if (stopped) return tail;
      stopped = true;
      connected = false;
      if (timer) { cancel(timer); timer = undefined; }
      return enqueue(async () => { if (initialized) await choose(4); });
    },
  };
}
