// The pinned SDK predates botActivity. Use the additive Connect JSON field;
// the key stays in this integration process and is never sent to EVE's browser.
const PRIORITY = { THINKING: 1, WRITING: 2, TOOL_USE: 3, WEB_RESEARCH: 4 };

export function createBotActivityReporter({ serverUrl, botId, apiKey, validate = async () => {},
  fetchImpl = globalThis.fetch, intervalMs = 3000, timeoutMs = 1500, idleTimeoutMs = 1000,
  snapshotTtlMs = 4500, signal }) {
  const endpoint = new URL('/api/connect/chatto.api.v1.RoomService/RefreshTypingIndicator', serverUrl);
  const works = new Map(), slots = new Map();
  let timer, snapshotTimer, stopped = false, connected = true, stopping;
  const category = value => Object.hasOwn(PRIORITY, value) ? value : 'THINKING';
  function key(target) {
    if (target.server_url !== serverUrl || (target.bot_id && target.bot_id !== botId) || !target.room_id) return null;
    return JSON.stringify([serverUrl, botId, target.room_id, target.thread_root_id || '']);
  }
  async function drain(slot) {
    while (slot.pending) {
      slot.pending = false;
      const { activity, version, target } = slot;
      // Independent of both the work's cancellation and the process stop signal.
      const requestSignal = AbortSignal.timeout(activity === 'IDLE' ? idleTimeoutMs : timeoutMs);
      try {
        if (activity !== 'IDLE') await validate(target, requestSignal);
        // Validation may yield while newer events coalesce into this slot.
        if (version !== slot.version) continue;
        const response = await fetchImpl(endpoint, {
          method: 'POST', redirect: 'error', signal: requestSignal,
          headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json',
            'Connect-Protocol-Version': '1' },
          body: JSON.stringify({ roomId: target.room_id,
            ...(target.thread_root_id ? { threadRootEventId: target.thread_root_id } : {}),
            botActivity: `BOT_ACTIVITY_${activity}` }),
        });
        await response.body?.cancel();
        if (!response.ok) throw new Error('Activity rejected');
      } catch { /* Best effort; only a later live heartbeat retries. No payload logging. */ }
    }
  }
  function queue(target, activity, refresh = false) {
    const id = key(target);
    if (!id) return;
    let slot = slots.get(id);
    if (!slot) {
      slot = { target, activity: null, version: 0, pending: false, flight: null };
      slots.set(id, slot);
    }
    slot.target = target;
    if (slot.activity !== activity || refresh) {
      slot.activity = activity;
      slot.version++;
      slot.pending = true;
    }
    if (!slot.flight && slot.pending) {
      slot.flight = drain(slot).finally(() => {
        slot.flight = null;
        if (slot.pending) {
          queue(slot.target, slot.activity);
          return slot.flight;
        }
        if (slot.activity === 'IDLE' && !slot.pending) slots.delete(id);
      });
    }
  }
  function reconcile(refresh = false) {
    const targets = new Map();
    if (connected && !stopped) for (const work of works.values()) {
      const id = key(work.target);
      if (!id) continue;
      const previous = targets.get(id);
      if (!previous || PRIORITY[work.activity] > PRIORITY[previous.activity]) targets.set(id, work);
    }
    for (const [id, slot] of slots) if (!targets.has(id)) queue(slot.target, 'IDLE');
    for (const work of targets.values()) queue(work.target, work.activity, refresh);
    if (works.size && connected && !stopped && !timer) {
      timer = setInterval(() => reconcile(true), intervalMs);
      timer.unref?.();
    } else if ((!works.size || !connected || stopped) && timer) {
      clearInterval(timer); timer = undefined;
    }
  }
  function syncJobs(jobs) {
    if (stopped || !connected) return;
    for (const [id, work] of works) if (work.job) works.delete(id);
    for (const job of jobs) if (['queued', 'running'].includes(job.state) && key(job.target)) {
      works.set(`job:${job.id}`, { job: true, target: { ...job.target }, activity: category(job.progress?.bot_activity) });
    }
    clearTimeout(snapshotTimer);
    snapshotTimer = undefined;
    // A dead/restarted EVE bridge must not keep old snapshots alive indefinitely.
    if (jobs.some(job => ['queued', 'running'].includes(job.state))) {
      snapshotTimer = setTimeout(() => syncJobs([]), snapshotTtlMs);
      snapshotTimer.unref?.();
    }
    reconcile();
  }
  function acceptJob(id, target) {
    if (stopped || !connected || !key(target)) return;
    works.set(`job:${id}`, { job: true, target: { ...target }, activity: 'THINKING' });
    if (!snapshotTimer) {
      snapshotTimer = setTimeout(() => syncJobs([]), snapshotTtlMs);
      snapshotTimer.unref?.();
    }
    reconcile();
  }
  function begin(target, activity = 'THINKING', workSignal) {
    const id = Symbol('work');
    const end = () => {
      workSignal?.removeEventListener('abort', end);
      works.delete(id);
      reconcile();
    };
    if (!stopped && !workSignal?.aborted && key(target)) {
      works.set(id, { target: { ...target }, activity: category(activity), cleanup: () => workSignal?.removeEventListener('abort', end) });
      workSignal?.addEventListener('abort', end, { once: true });
      reconcile();
    }
    return { end, update: value => { const work = works.get(id); if (work) { work.activity = category(value); reconcile(); } } };
  }
  function setConnected(value) {
    if (stopped || connected === Boolean(value)) return;
    connected = Boolean(value);
    if (!connected) {
      clearTimeout(snapshotTimer);
      snapshotTimer = undefined;
      for (const [id, work] of works) if (work.job) works.delete(id);
    }
    reconcile();
  }
  function stop() {
    if (stopping) return stopping;
    stopped = true;
    signal?.removeEventListener('abort', onAbort);
    clearTimeout(snapshotTimer);
    snapshotTimer = undefined;
    for (const work of works.values()) work.cleanup?.();
    works.clear();
    reconcile();
    stopping = Promise.all([...slots.values()].map(slot => slot.flight)).then(() => {});
    return stopping;
  }
  const onAbort = () => { void stop(); };
  if (signal?.aborted) void stop();
  else signal?.addEventListener('abort', onAbort, { once: true });
  return { begin, acceptJob, syncJobs, setConnected, stop,
    async withWork(target, work, workSignal) {
      const handle = begin(target, 'THINKING', workSignal);
      try { return await work(); } finally { handle.end(); }
    },
  };
}
