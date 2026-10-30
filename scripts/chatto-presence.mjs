// Use Chatto's Away color for active requests, Online for an idle connection.
const ONLINE = 1, WORKING = 2, OFFLINE = 4;

export function createBotPresence(api, {
  schedule = setInterval, cancel = clearInterval, onError = () => {},
  readActivity, pollSchedule = setTimeout, pollCancel = clearTimeout,
} = {}) {
  let connected = false;
  let stopped = false;
  let timer;
  let tail = Promise.resolve();
  let appliedStatus;
  let activeWork = 0;
  let eveWorking = false;
  let pollTimer;
  let generation = 0;
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
  function tick(refresh = true) {
    return enqueue(async () => {
      if (!connected || stopped) return;
      const desiredStatus = activeWork || eveWorking ? WORKING : ONLINE;
      // Only connection/activity transitions write preferences. Retry failed writes.
      if (appliedStatus !== desiredStatus) {
        await choose(desiredStatus);
        appliedStatus = desiredStatus;
        refresh = true;
      }
      if (refresh) await api.refreshPresence({}, options);
    });
  }
  // Poll independently of Chatto messages. Keep the last known state on read errors;
  // a failed read must not claim that ongoing EVE work has finished.
  async function pollActivity(epoch) {
    try {
      const activity = await readActivity();
      if (typeof activity?.working !== 'boolean') throw new Error('Invalid EVE activity');
      if (epoch !== generation || stopped || !connected) return;
      eveWorking = activity.working;
      await tick(false);
    } catch {
      if (epoch === generation && !stopped && connected) onError();
    }
    if (epoch === generation && !stopped && connected) {
      pollTimer = pollSchedule(() => pollActivity(epoch), 1000);
    }
  }
  return {
    setConnected(value) {
      if (stopped || connected === value) return tail;
      connected = value;
      generation++;
      if (timer) { cancel(timer); timer = undefined; }
      if (pollTimer) { pollCancel(pollTimer); pollTimer = undefined; }
      if (!value) return tail;
      appliedStatus = undefined;
      timer = schedule(() => tick(), 30000);
      if (readActivity) void pollActivity(generation);
      return tick();
    },
    // Count overlapping requests; errors and cancellation always release the slot.
    // The caller includes image loading, model/tools, and answer delivery in work.
    async withWork(work) {
      activeWork++;
      try {
        await tick();
        return await work();
      } finally {
        activeWork--;
        await tick();
      }
    },
    stop() {
      if (stopped) return tail;
      stopped = true;
      connected = false;
      generation++;
      if (timer) { cancel(timer); timer = undefined; }
      if (pollTimer) { pollCancel(pollTimer); pollTimer = undefined; }
      return enqueue(async () => { if (appliedStatus !== undefined) await choose(OFFLINE); });
    },
  };
}
