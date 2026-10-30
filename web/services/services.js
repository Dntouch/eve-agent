(() => {
  "use strict";
  if (new URLSearchParams(window.location.search).has("embedded")) document.body.classList.add("embedded");
  const labels = {healthy: "BEREIT", warning: "EINGESCHRÄNKT", error: "GESTÖRT", unavailable: "NICHT ERREICHBAR", stopped: "GESTOPPT", disabled: "DEAKTIVIERT", starting: "STARTET"};
  const actions = {start: "Starten", stop: "Stoppen", restart: "Neustarten"};
  const names = {eve: "EVE", llm: "Sprachmodell", search: "Websuche", chatto: "Chatto"};
  let fetching = false;
  let submitting = false;
  let lastOperation = null;
  const el = (id) => document.getElementById(id);
  const node = (tag, text, cls) => {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    if (cls) result.className = cls;
    return result;
  };
  function connectionError(message) {
    el("connection").hidden = !message;
    el("connection").textContent = message;
  }
  function markUnknown() {
    for (const card of el("services").querySelectorAll(".service")) {
      card.dataset.status = "unavailable";
      card.querySelector(".status").textContent = "UNBEKANNT";
      card.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    }
  }
  async function request(payload) {
    const response = await fetch("/api/services", {
      method: payload ? "POST" : "GET", cache: "no-store", signal: AbortSignal.timeout(8000),
      headers: payload ? {"Content-Type": "application/json"} : {},
      ...(payload ? {body: JSON.stringify(payload)} : {}),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }
  function render(data) {
    const priority = {error: 0, unavailable: 0, warning: 1, stopped: 2, starting: 2, healthy: 3, disabled: 4};
    const rows = [...(data.services || [])].sort((left, right) =>
      (priority[left.status] ?? 4) - (priority[right.status] ?? 4));
    const problems = rows.filter((row) => ["error", "unavailable", "warning"].includes(row.status));
    const stopped = rows.filter((row) => row.status === "stopped");
    el("summary").textContent = data.checking ? "Dienste werden geprüft …" :
      problems.length ? `${problems.length} Dienst${problems.length === 1 ? " benötigt" : "e benötigen"} Aufmerksamkeit` :
      stopped.length ? `${stopped.length} Dienst${stopped.length === 1 ? " ist" : "e sind"} gestoppt` : "Alle aktivierten Dienste sind bereit";
    let stale = false;
    if (data.checked_at) {
      const time = new Date(data.checked_at);
      stale = Date.now() - time.getTime() > 45000;
      el("checked").textContent = `Letzte Prüfung: ${time.toLocaleString("de-DE")} · automatisch alle ${data.refresh_seconds || 15} Sekunden`;
      if (stale) {
        el("summary").textContent = "Status veraltet · erneute Prüfung ausstehend";
        connectionError("Die letzte Dienstprüfung ist älter als 45 Sekunden. Angezeigte Zustände sind möglicherweise nicht mehr aktuell.");
      }
    }
    const url = new URL(window.location.href);
    url.port = String(data.eve_port || Number(url.port) - 2);
    url.pathname = "/"; url.search = ""; url.hash = "";
    el("eveLink").href = url.href;
    lastOperation = data.operation;
    const busy = submitting || lastOperation?.status === "running";
    el("operation").hidden = !lastOperation;
    if (lastOperation) {
      el("operation").dataset.status = lastOperation.status;
      const status = {running: "Läuft", completed: "Abgeschlossen", failed: "Fehlgeschlagen"}[lastOperation.status] || lastOperation.status;
      el("operation").textContent = `${names[lastOperation.service] || lastOperation.service} · ${actions[lastOperation.action]}: ${status}. ${lastOperation.detail || "Status wird weiter geprüft."}`;
    }
    const fragment = document.createDocumentFragment();
    for (const row of rows) {
      const card = node("article", undefined, "service");
      card.dataset.status = row.status;
      const head = node("div", undefined, "service-head");
      head.append(node("h2", row.title), node("span", labels[row.status] || row.status, "status"));
      card.append(head, node("p", row.detail, "detail"));
      if (row.issues?.length) {
        const issues = node("ul", undefined, "note");
        for (const issue of row.issues) issues.append(node("li", issue));
        card.append(issues);
      }
      if (row.scopes) card.append(node("p", Object.entries(row.scopes).map(([key, allowed]) =>
        `${({web_chat: "Webchat", owner_dm: "Eigene DM", member_dm: "Mitglieder-DM", channels: "Channels"})[key] || key}: ${allowed ? "freigegeben" : "gesperrt"}`).join(" · "), "scopes"));
      if (row.last_event_at) card.append(node("p", "Aufruf vom " + new Date(row.last_event_at).toLocaleString("de-DE"), "note"));
      if (row.control_note) card.append(node("p", row.control_note, "note"));
      const controls = node("div", undefined, "actions");
      for (const action of row.actions || []) {
        const button = node("button", actions[action]);
        button.type = "button"; button.dataset.action = action;
        button.setAttribute("aria-label", `${row.title}: ${actions[action]}`);
        button.disabled = busy;
        button.addEventListener("click", () => operate(row.id, action));
        controls.append(button);
      }
      card.append(controls); fragment.append(card);
    }
    // Keep keyboard focus through automatic refreshes.
    const focused = document.activeElement;
    const focusKey = focused?.getAttribute("aria-label");
    el("services").replaceChildren(fragment);
    if (stale) markUnknown();
    if (focusKey && focused?.tagName === "BUTTON") {
      [...el("services").querySelectorAll("button")].find((button) => button.getAttribute("aria-label") === focusKey)?.focus();
    }
  }
  async function refresh() {
    if (fetching) return;
    fetching = true;
    try { const data = await request(); connectionError(""); render(data); }
    catch (error) {
      connectionError(`Dienstkonsole nicht erreichbar: ${error.message}. Status ist unbekannt.`);
      el("summary").textContent = "Verbindung zur Dienstkonsole unterbrochen";
      markUnknown();
    } finally { fetching = false; }
  }
  async function operate(service, action) {
    if (submitting || lastOperation?.status === "running") return;
    submitting = true;
    el("services").querySelectorAll("button").forEach((button) => { button.disabled = true; });
    let failure = "";
    try { await request({service, action}); }
    catch (error) { failure = error.message; }
    finally { submitting = false; await refresh(); if (failure) connectionError(failure); }
  }
  el("refresh").addEventListener("click", refresh);
  async function poll() { await refresh(); window.setTimeout(poll, 2000); }
  poll();
})();
