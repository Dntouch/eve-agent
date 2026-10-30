"""Independent, bounded service monitoring and control for this EVE installation."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .config import load_config
from .memory import redact_sensitive
from .transport_access import PUBLIC_CAPABILITIES


def console_port(cfg):
    default = int(cfg["visual"]["port"]) + 2
    port = int(os.environ.get("EVE_SERVICE_PORT", default if default <= 65535 else default - 4))
    if not 1 <= port <= 65535 or port == int(cfg["visual"]["port"]):
        raise ValueError("Dienstkonsole benötigt einen eigenen gültigen Port")
    return port


def local_url(cfg, *, console=False):
    visual = cfg["visual"]
    scheme = "https" if visual.get("tls_cert") and visual.get("tls_key") else "http"
    host = visual["host"]
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1" if host == "0.0.0.0" else "::1"
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}:{console_port(cfg) if console else visual['port']}"


def request_json(url, *, payload=None, headers=None, timeout=4, local_tls=False):
    request = urllib.request.Request(url, headers=headers or {},
        data=json.dumps(payload).encode() if payload is not None else None)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
    context = ssl._create_unverified_context() if local_tls else None
    with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("Statusantwort ist zu groß")
        return json.loads(raw)


def runtime_status(agent, chatto, cfg):
    """Facts from the live runtime, independent of what the model says about itself."""
    result = {
        "web_registered": getattr(agent, "web", None) is not None,
        "web_scopes": {"web_chat": True, "owner_dm": True,
                       "member_dm": "web" in PUBLIC_CAPABILITIES,
                       "channels": "web" in cfg["chatto"]["channel_capabilities"]},
        "chatto": chatto.status(),
    }
    path = cfg["paths"]["database"]
    try:
        with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1) as conn:
            row = conn.execute(
                "SELECT capability, operation, updated_at FROM memory_work_calls "
                "WHERE capability='web' OR (capability='unknown' AND "
                "(operation='web' OR operation LIKE 'web__%')) ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row:
                result["last_web_call"] = {"capability": row[0], "operation": row[1], "at": row[2],
                    "invalid_function": row[0] == "unknown"}
    except (OSError, sqlite3.Error):
        pass
    return result


class ServiceManager:
    def __init__(self, root, config_path):
        self.root, self.config_path = Path(root).resolve(), Path(config_path).resolve()
        self.runtime = self.root / "runtime" / "services"
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._snapshot = None
        self._operation = None
        self._search_probe = None
        self._stop = threading.Event()

    @staticmethod
    def _row(identifier, title, status, detail, *, actions=(), **extra):
        return {"id": identifier, "title": title, "status": status, "detail": detail,
                "actions": list(actions), **extra}

    @staticmethod
    def _error(exc):
        # URLs with credentials and provider tokens must never reach the UI/log.
        if isinstance(exc, urllib.error.HTTPError):
            return f"HTTP {exc.code}"
        if isinstance(exc, urllib.error.URLError):
            return redact_sensitive(str(exc.reason))[:240]
        return redact_sensitive(str(exc))[:240]

    def _container(self, cfg, identifier):
        section = cfg["web"] if identifier == "search" else cfg["llm"]
        url = urllib.parse.urlsplit(section["searxng_url" if identifier == "search" else "base_url"])
        if url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            return None
        port = url.port or (443 if url.scheme == "https" else 80)
        names = (["eve-search-" + hashlib.sha256(str(self.root).encode()).hexdigest()[:12], "eve-searxng"]
                 if identifier == "search" else ["eve-strata"])
        for engine in ("podman", "docker"):
            executable = shutil.which(engine)
            if not executable:
                continue
            for name in names:
                try:
                    proc = subprocess.run([executable, "container", "inspect", name],
                        capture_output=True, text=True, timeout=3, check=False)
                    if proc.returncode:
                        continue
                    container = json.loads(proc.stdout)[0]
                    bindings = (container.get("HostConfig", {}).get("PortBindings") or {})
                    matches = any(str(binding.get("HostPort")) == str(port)
                        and binding.get("HostIp", "") in {"", "127.0.0.1", "0.0.0.0", "::", "::1"}
                        for values in bindings.values() for binding in (values or []))
                    if container.get("HostConfig", {}).get("NetworkMode") == "host":
                        environment = dict(value.split("=", 1) for value in
                            container.get("Config", {}).get("Env", []) if "=" in value)
                        matches = environment.get("PORT") == str(port)
                    if matches:
                        return {"engine": executable, "name": name,
                                "running": bool(container.get("State", {}).get("Running"))}
                except (OSError, ValueError, subprocess.TimeoutExpired, KeyError, IndexError):
                    continue
        return None

    def _eve(self, cfg):
        actions = ("start", "stop", "restart") if all(
            (self.root / f"desktop-{action}.sh").is_file() for action in ("start", "stop")) else ()
        try:
            request_json(local_url(cfg) + "/health/live", local_tls=True)
        except (OSError, ValueError) as exc:
            return self._row("eve", "EVE", "unavailable", "Nicht erreichbar: " + self._error(exc), actions=actions)
        try:
            ready = request_json(local_url(cfg) + "/health/ready", local_tls=True)
            return self._row("eve", "EVE", "healthy" if ready.get("ready") else "warning",
                "Bereit" if ready.get("ready") else "Prozess läuft; Sprachmodell noch nicht bereit", actions=actions)
        except (OSError, ValueError):
            return self._row("eve", "EVE", "warning", "Prozess läuft; Bereitschaftsprüfung fehlgeschlagen", actions=actions)

    def _http_service(self, cfg, identifier):
        section = cfg["web"] if identifier == "search" else cfg["llm"]
        title = "Websuche · SearXNG" if identifier == "search" else "Sprachmodell · LLM"
        if identifier == "search" and not section.get("enabled"):
            return self._row(identifier, title, "disabled", "In EVEs Konfiguration deaktiviert")
        container = self._container(cfg, identifier)
        actions = ("start", "stop", "restart") if container else ()
        control_note = "" if container else "Externer Dienst; auf dessen Host verwalten."
        if container and not container["running"]:
            return self._row(identifier, title, "stopped", "Container gestoppt", actions=actions)
        start = time.monotonic()
        issues = []
        try:
            base = section["searxng_url" if identifier == "search" else "base_url"].rstrip("/")
            if identifier == "search":
                metadata = request_json(base + "/config")
                if not isinstance(metadata.get("engines"), list):
                    raise ValueError("Suchdienst liefert keine gültigen API-Metadaten")
                probe = self._search_probe
                if not probe or probe["base"] != base or time.monotonic() - probe["at"] >= 300:
                    result = request_json(base + "/search?" + urllib.parse.urlencode(
                        {"q": "Python documentation", "format": "json", "language": "de-DE"}), timeout=8)
                    self._search_probe = {"base": base, "at": time.monotonic(), "result": result}
                else:
                    result = probe["result"]
                if not isinstance(result.get("results"), list):
                    raise ValueError("Suchdienst liefert keine JSON-Ergebnisliste")
                count = len(result["results"])
                state = "healthy" if count else "warning"
                detail = f"JSON-Suche erfolgreich · {count} Treffer" if count else "Suchdienst antwortet, liefert aber keine Treffer"
                if result.get("unresponsive_engines"):
                    count = len(result["unresponsive_engines"])
                    detail += f" · {count} " + ("Suchmaschine gestört" if count == 1 else "Suchmaschinen gestört")
                    issues = [": ".join(map(str, item)) if isinstance(item, list) else str(item)
                              for item in result["unresponsive_engines"]]
                    state = "warning"
                control_note = (control_note + " API-Prüfung alle 15 Sekunden; Suchprobe alle 5 Minuten.").strip()
            else:
                result = request_json(base + "/models", headers={"Authorization": "Bearer " + section.get("api_key", "local")})
                configured = section["model"].casefold().rsplit("/", 1)[-1]
                models = [str(item.get("id", "")).casefold().rsplit("/", 1)[-1] for item in result.get("data", [])]
                state = "healthy" if configured in models else "warning"
                detail = "Modell bereit: " + section["model"] if state == "healthy" else "Server erreichbar; konfiguriertes Modell nicht geladen"
            return self._row(identifier, title, state, detail, actions=actions, control_note=control_note,
                latency_ms=round((time.monotonic() - start) * 1000), issues=issues)
        except (OSError, ValueError, TypeError) as exc:
            return self._row(identifier, title, "error", "Prüfung fehlgeschlagen: " + self._error(exc),
                actions=actions, control_note=control_note)

    def _runtime_rows(self, cfg):
        try:
            runtime = request_json(local_url(cfg) + "/api/services/runtime", local_tls=True)
        except (OSError, ValueError):
            return [self._row("web_access", "Web-Werkzeuge im Chat", "unavailable", "Laufzeitstatus nicht erreichbar"),
                    self._row("chatto", "Chatto", "unavailable", "EVE muss für die Bot-Steuerung laufen")]
        registered = runtime.get("web_registered")
        last = runtime.get("last_web_call") or {}
        web = self._row("web_access", "Web-Werkzeuge im Chat", "healthy" if registered else "disabled",
            "Im laufenden EVE-Prozess verfügbar" if registered else "Im laufenden EVE-Prozess nicht registriert",
            scopes=runtime.get("web_scopes", {}))
        if registered and last.get("invalid_function"):
            web.update(status="warning", detail=("Letzter Webversuch: ungültiger Funktionsname „" + last["operation"]
                + "“. Kein Suchdienst aufgerufen; keine verweigerte Berechtigung."), last_event_at=last.get("at"))
        chatto = runtime.get("chatto") or {}
        state = chatto.get("state", "unknown")
        chatto_row = self._row("chatto", "Chatto", {"ready": "healthy", "disabled": "disabled", "stopped": "stopped",
            "starting": "starting", "connecting": "starting"}.get(state, "error"),
            {"ready": "Bot verbunden", "disabled": "In EVE deaktiviert", "stopped": "Bot gestoppt"}.get(state, "Botstatus: " + state),
            actions=("start", "stop", "restart") if cfg["chatto"].get("enabled") else ())
        return [web, chatto_row]

    def _external(self, cfg, identifier):
        section = cfg[identifier]
        title = {"home_assistant": "Home Assistant", "image_generation": "Bildgenerierung"}[identifier]
        if not section.get("enabled"):
            return self._row(identifier, title, "disabled", "In EVE deaktiviert")
        try:
            if identifier == "home_assistant":
                request_json(section["url"].rstrip("/") + "/api/",
                    headers={"Authorization": "Bearer " + section.get("token", "")})
            else:
                path = "/sdapi/v1/options" if section.get("api_format") == "sdapi" else "/models"
                request_json(section["base_url"].rstrip("/") + path,
                    headers={"Authorization": "Bearer " + section.get("api_key", "")})
            return self._row(identifier, title, "healthy", "API erreichbar", control_note="Auf dem Dienst-Host verwalten.")
        except (OSError, ValueError) as exc:
            return self._row(identifier, title, "error", self._error(exc), control_note="Auf dem Dienst-Host verwalten.")

    def _speech(self, cfg):
        section = cfg["text_to_speech"]
        engine = section["engine"]
        if engine in {"qwen3_tts", "chatterbox"}:
            try:
                request_json(section[engine + "_url"].rstrip("/") + "/health")
                return self._row("speech", "Sprachausgabe", "healthy", engine + " · API erreichbar",
                    control_note="Der lokale Sprachserver startet und stoppt zusammen mit EVE.")
            except (OSError, ValueError) as exc:
                return self._row("speech", "Sprachausgabe", "warning", engine + " nicht erreichbar: " + self._error(exc),
                    control_note="Piper-Fallback möglich; lokalen Sprachserver über EVE neu starten.")
        voice = self.root / section["data_dir"] / (section["voice"] + ".onnx")
        available = voice.is_file() and voice.with_suffix(".onnx.json").is_file()
        return self._row("speech", "Sprachausgabe · Piper", "healthy" if available else "error",
            "Stimmdateien vorhanden · in EVE integriert" if available else "Stimmdateien fehlen",
            control_note="Kein separater Dienst. Dies ist eine Dateiprüfung; Steuerung über EVE.")

    def refresh(self):
        if not self._refresh_lock.acquire(blocking=False):
            return
        try:
            _, cfg = load_config(self.config_path)
            checks = [lambda: [self._eve(cfg)], lambda: [self._http_service(cfg, "llm")],
                      lambda: [self._http_service(cfg, "search")], lambda: self._runtime_rows(cfg),
                      lambda: [self._external(cfg, "home_assistant")], lambda: [self._external(cfg, "image_generation")],
                      lambda: [self._speech(cfg)]]
            with ThreadPoolExecutor(max_workers=6) as pool:
                rows = [row for group in pool.map(lambda check: check(), checks) for row in group]
            snapshot = {"services": rows, "checked_at": datetime.now(timezone.utc).isoformat(),
                        "console_port": console_port(cfg), "eve_port": cfg["visual"]["port"],
                        "instance_id": hashlib.sha256(str(self.root).encode()).hexdigest()[:12],
                        "refresh_seconds": 15}
            with self._lock:
                self._snapshot = snapshot
        finally:
            self._refresh_lock.release()

    def snapshot(self):
        with self._lock:
            result = deepcopy(self._snapshot) or {"services": [], "checking": True}
            result["operation"] = deepcopy(self._operation)
            result["instance_id"] = hashlib.sha256(str(self.root).encode()).hexdigest()[:12]
        return result

    def monitor(self):
        while not self._stop.is_set():
            try:
                self.refresh()
            except Exception:
                # Never leave an old green status after a configuration/probe failure.
                with self._lock:
                    self._snapshot = {"services": [], "error": "Dienstprüfung fehlgeschlagen; Konfiguration und Konsolenprotokoll prüfen."}
                import traceback
                traceback.print_exc()
            self._stop.wait(15)

    def action(self, payload):
        if set(payload) != {"service", "action"} or payload["action"] not in {"start", "stop", "restart"}:
            raise ValueError("Erwartet werden service und action (start, stop, restart)")
        identifier, action = payload["service"], payload["action"]
        if identifier not in {"eve", "llm", "search", "chatto"}:
            raise ValueError("Dieser Dienst wird nicht lokal verwaltet")
        with self._lock:
            if self._operation and self._operation["status"] == "running":
                return 409, {"error": "Eine Dienstaktion läuft bereits", "operation": deepcopy(self._operation)}
            self._operation = {"service": identifier, "action": action, "status": "running",
                               "started_at": datetime.now(timezone.utc).isoformat()}
        threading.Thread(target=self._perform, args=(identifier, action), daemon=True).start()
        return 202, {"operation": self.snapshot()["operation"]}

    def _command(self, argv):
        env = {**os.environ, "EVE_DESKTOP_NOTIFICATIONS": "0", "EVE_SERVICE_CONSOLE": "0",
               "EVE_SKIP_AUXILIARY": "1"}
        proc = subprocess.run(argv, cwd=self.root, env=env, capture_output=True, text=True, timeout=240)
        if proc.returncode:
            raise RuntimeError(f"Steuerung endete mit Code {proc.returncode}: " + (proc.stderr or proc.stdout)[-600:])

    def _perform(self, identifier, action):
        try:
            _, cfg = load_config(self.config_path)
            if identifier == "chatto":
                result = request_json(local_url(cfg) + "/api/services/runtime", local_tls=True,
                    payload={"service": "chatto", "action": action}, timeout=20)
                if result.get("error"):
                    raise RuntimeError(result["error"])
            elif identifier == "eve":
                for step in (["stop", "start"] if action == "restart" else [action]):
                    script = self.root / f"desktop-{step}.sh"
                    if not script.is_file():
                        raise ValueError("Lokaler EVE-Launcher fehlt")
                    self._command(["bash", str(script)])
            else:
                container = self._container(cfg, identifier)
                if container is None:
                    raise ValueError("Kein eindeutig zu diesem lokalen Endpunkt gehörender Container gefunden")
                argv = [container["engine"], action]
                if action in {"stop", "restart"}:
                    argv += ["--time", "30" if identifier == "llm" else "5"]
                self._command([*argv, container["name"]])
            detail, status = "Steuerbefehl abgeschlossen. Der Dienststatus wird erneut geprüft.", "completed"
        except Exception as exc:
            detail, status = self._error(exc), "failed"
        with self._lock:
            self._operation.update(status=status, detail=detail, completed_at=datetime.now(timezone.utc).isoformat())
            receipt = deepcopy(self._operation)
        with (self.runtime / "actions.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
        self.refresh()

    def handle(self, method, path, payload):
        if path != "/api/services":
            return 404, {"error": "Unbekannter Dienstendpunkt"}
        if method == "GET":
            return 200, self.snapshot()
        if method == "POST":
            return self.action(payload)
        return 405, {"error": "Methode ist nicht erlaubt"}


def ensure_console(root, config_path):
    _, cfg = load_config(config_path)
    expected = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:12]
    state = None
    try:
        state = request_json(local_url(cfg, console=True) + "/api/services", local_tls=True, timeout=1)
    except (OSError, ValueError):
        pass
    if state is not None:
        if state.get("instance_id") != expected:
            raise ValueError("Der Konsolenport gehört zu einer anderen Installation")
        return
    runtime = Path(root) / "runtime" / "services"
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime / "console.log").open("a") as log:
        process = subprocess.Popen([sys.executable, "-m", "eve_agent.services", "--config", str(config_path)],
            cwd=root, env={**os.environ, "PYTHONPATH": str(Path(root) / "src")},
            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)
    for _ in range(20):
        try:
            state = request_json(local_url(cfg, console=True) + "/api/services", local_tls=True, timeout=1)
            if state.get("instance_id") == expected:
                return
        except (OSError, ValueError):
            pass
        if process.poll() is not None:
            break
        time.sleep(0.15)
    raise RuntimeError("Dienstkonsole nicht bereit; runtime/services/console.log prüfen")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--ensure", action="store_true")
    args = parser.parse_args()
    root, cfg = load_config(args.config)
    if args.ensure:
        ensure_console(root, args.config.resolve())
        return
    from .state import StateBus
    from .visual import VisualServer
    manager = ServiceManager(root, args.config)
    lock_path = manager.runtime / "console.lock"
    with lock_path.open("a") as lock:
        if os.name == "posix":
            import fcntl
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
        visual = cfg["visual"]
        server = VisualServer(root / "web" / "services", StateBus(manager.runtime), visual["host"], console_port(cfg),
            tls_cert=Path(visual["tls_cert"]) if visual.get("tls_cert") else None,
            tls_key=Path(visual["tls_key"]) if visual.get("tls_key") else None,
            allowed_hosts=[*visual.get("allowed_hosts", []), visual.get("public_host", "")],
            service_handler=manager.handle)
        server.start()
        threading.Thread(target=manager.monitor, daemon=True).start()
        try:
            from .cli import _wait_for_service_shutdown
            _wait_for_service_shutdown()
        finally:
            manager._stop.set()
            server.stop()


if __name__ == "__main__":
    main()
