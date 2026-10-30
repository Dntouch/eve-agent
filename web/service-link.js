(() => {
  "use strict";
  const link = document.getElementById("openServices");
  if (!link) return;
  const dialog = document.createElement("dialog");
  dialog.id = "serviceDialog";
  dialog.className = "service-dialog";
  dialog.setAttribute("aria-labelledby", "serviceDialogTitle");
  const header = document.createElement("header");
  header.className = "service-dialog-head";
  const heading = document.createElement("h2");
  heading.id = "serviceDialogTitle";
  heading.textContent = "Dienststatus & Steuerung";
  const standalone = document.createElement("a");
  standalone.textContent = "Unabhängige Konsole ↗";
  standalone.target = "_blank";
  standalone.rel = "noopener";
  standalone.title = "Bleibt auch nach dem Stoppen von EVE erreichbar";
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "×";
  close.setAttribute("aria-label", "Dienstübersicht schließen");
  close.addEventListener("click", () => dialog.close());
  header.append(heading, standalone, close);
  const frame = document.createElement("iframe");
  frame.title = "Dienstmeldungen und Start-, Stopp- und Neustartsteuerung";
  dialog.append(header, frame);
  document.body.append(dialog);
  link.setAttribute("aria-haspopup", "dialog");
  link.setAttribute("aria-controls", dialog.id);
  link.setAttribute("aria-label", "Dienstmeldungen und Steuerung anzeigen");
  link.addEventListener("click", (event) => {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const menu = document.getElementById("systemMenuToggle");
    if (menu?.getAttribute("aria-expanded") === "true") menu.click();
    if (!frame.getAttribute("src")) frame.src = "services/index.html?embedded=1";
    dialog.showModal();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
  });
  dialog.addEventListener("close", () => link.focus());
  function setPort(port) {
    const url = new URL(window.location.origin);
    url.port = String(port);
    link.href = url.href;
    standalone.href = url.href;
  }
  setPort(Number(window.location.port || (window.location.protocol === "https:" ? 443 : 80)) + 2);
  async function update() {
    try {
      const response = await fetch("/api/services", {cache: "no-store", signal: AbortSignal.timeout(4000)});
      const data = await response.json();
      if (data.console_port) setPort(data.console_port);
      if (!response.ok || data.error || !data.checked_at || Date.now() - new Date(data.checked_at).getTime() > 45000) throw new Error();
      const rows = data.services || [];
      const bad = rows.filter((row) => ["error", "unavailable"].includes(row.status));
      const warnings = rows.filter((row) => ["warning", "stopped", "starting"].includes(row.status));
      link.dataset.status = bad.length ? "error" : warnings.length ? "warning" : "healthy";
      link.textContent = bad.length ? `Dienste · ${bad.length} gestört` : warnings.length ? `Dienste · ${warnings.length} Hinweise` : "Dienste · bereit";
      link.title = "Klicken für Dienstmeldungen und Steuerung";
    } catch (_) {
      link.dataset.status = "unknown";
      link.textContent = "Dienste · Status unbekannt";
      link.title = "Klicken für Dienstübersicht und Zugang zur unabhängigen Konsole";
    }
    window.setTimeout(update, 15000);
  }
  update();
})();
