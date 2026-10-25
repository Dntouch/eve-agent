/* Actual temporary learning objects and calls, projected separately from claims. */
(() => {
  "use strict";
  class WorkingMemoryLayer {
    constructor({read, render, status, active, interval = 3000}) {
      Object.assign(this, {read, render, status, active, interval});
      this.snapshot = null;
      this.seen = new Set();
      this.timer = null;
      this.busy = false;
      this.generation = 0;
    }
    async poll() {
      if (this.busy || !this.active()) return;
      this.busy = true;
      const generation = this.generation;
      try {
        const snapshot = await this.read();
        if (generation !== this.generation || !this.active()) return;
        if (snapshot.version !== "working-memory-graph-v1") throw new Error("Unbekannte Arbeitsansicht");
        const now = Date.now();
        const impulses = this.snapshot ? (snapshot.events || []).filter(event => {
          const age = now - Date.parse(event.occurred_at);
          return !this.seen.has(event.id) && age >= -1000 && age <= 10000;
        }) : [];
        this.seen = new Set((snapshot.events || []).map(event => event.id));
        this.snapshot = snapshot;
        this.render(snapshot, impulses);
      } catch (error) {
        if (generation === this.generation && this.active()) this.status(`Kurzzeitgedächtnis: ${error.message} · Ansicht möglicherweise veraltet`);
      } finally {
        this.busy = false;
      }
    }
    sync() {
      this.stop();
      if (!this.active()) return;
      this.poll();
      this.timer = setInterval(() => this.poll(), this.interval);
    }
    stop() {
      this.generation += 1;
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
    }
    clear() {
      this.stop();
      this.snapshot = null;
      this.seen.clear();
    }
  }
  function summary(snapshot) {
    const jobs = snapshot.jobs || {}, turns = snapshot.turns || [];
    const running = turns.filter(turn => turn.status === "running");
    const reads = running.reduce((sum, turn) => sum + Number(turn.reads || 0), 0);
    const frames = running.reduce((sum, turn) => sum + Number(turn.context_frames || 0), 0);
    const last = turns.map(turn => turn.last_activity_at).filter(Boolean).sort().at(-1);
    const activity = last ? new Date(last).toLocaleTimeString("de-DE") : "noch keine";
    return `${jobs.running || 0} in Verarbeitung · ${jobs.pending || 0} wartend · ${jobs.failed || 0} Lernversuche ohne Abschluss`
      + ` · ${reads} Lesezugriffe / ${frames} Kontextaufbauten im aktiven Arbeitsstand · letzte Aktivität ${activity}`;
  }
  window.EveWorkingMemoryCloud = {WorkingMemoryLayer, summary};
})();
