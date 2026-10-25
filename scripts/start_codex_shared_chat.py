#!/usr/bin/env python3
"""Start the installed desktop app on a shared local server after manual exit."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def launch_plan(codex_home):
    socket = Path(codex_home).resolve() / "app-server-control/app-server-control.sock"
    if any(character in str(socket) for character in (":", "?", "#", "%")):
        raise ValueError("Socket path contains URL delimiters; choose a plain Codex home path")
    return {
        "server": ["/usr/lib/chatgpt/resources/codex", "-c", "features.code_mode_host=true",
                   "app-server", "--listen", "unix://" + str(socket)],
        "socket": str(socket),
        "desktop": ["/usr/lib/chatgpt/ChatGPT"],
        "desktop_env": {"CODEX_APP_SERVER_WS_URL": f"ws+unix://localhost{socket}:/rpc"},
    }


def desktop_running():
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            args = (process / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if (args and args[0] == b"/usr/lib/chatgpt/ChatGPT"
                and not any(arg.startswith(b"--type=") for arg in args)):
            return True
    return False


def stop_child(child):
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def start_server(plan, environment=None):
    socket = Path(plan["socket"])
    socket.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if socket.exists():
        raise RuntimeError(f"Socket already exists: {socket}. No existing server was changed.")
    log_path = socket.parent / "eve-shared-server.log"
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a") as log:
        child = subprocess.Popen(plan["server"], stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, env=environment)
    try:
        deadline = time.monotonic() + 15
        while not socket.is_socket():
            if child.poll() is not None:
                raise RuntimeError(f"Server exited with {child.returncode}; see {log_path}")
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Server socket did not appear; see {log_path}")
            time.sleep(0.05)
        probe = Path(__file__).with_name("probe_codex_shared_chat.py")
        subprocess.run([sys.executable, str(probe), "--command", plan["server"][0],
                        "--socket", plan["socket"]], check=True, timeout=20, env=environment)
        return child
    except BaseException:
        stop_child(child)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        plan = launch_plan(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        if args.dry_run:
            print(json.dumps(plan, indent=2))
            return 0
        if os.environ.get("CODEX_APP_SERVER_FORCE_CLI") == "1":
            raise RuntimeError("CODEX_APP_SERVER_FORCE_CLI=1 prevents shared-server routing")
        if desktop_running():
            raise RuntimeError("Please fully quit the desktop app first. No process was stopped.")
        server = start_server(plan)
        try:
            environment = dict(os.environ, **plan["desktop_env"])
            print("Shared server connected. Keep this terminal open while using the app.", flush=True)
            return subprocess.run(plan["desktop"], env=environment).returncode
        finally:
            # Only terminate the server started by this launcher, after the app exits.
            stop_child(server)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"Shared-chat start failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
