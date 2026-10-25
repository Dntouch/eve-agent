#!/usr/bin/env python3
"""Probe the existing shared Codex WebSocket server; never launch a server."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from eve_agent.codex_chat import ProtocolError, SharedServer


def probe(client, cwd, create=False):
    client.request("initialize", {"clientInfo": {
        "name": "eve_shared_chat_probe", "version": "0.1.0"},
        "capabilities": {"experimentalApi": True}})
    client.send({"method": "initialized"})
    result = client.request("thread/list", {"limit": 1, "sourceKinds": []})
    report = {"connected": True, "desktop_visibility_verified": False,
              "threads_returned": len(result.get("data", []))}
    if create:
        workspace = Path(cwd).resolve()
        cursor = None
        matches = []
        while True:
            page = client.request("project/list", {"limit": 100, "cursor": cursor})
            for project in page.get("data", []):
                for root in project.get("roots", []):
                    path = Path(root["path"]).resolve()
                    if workspace == path or path in workspace.parents:
                        matches.append((len(path.parts), project["id"]))
            cursor = page.get("nextCursor")
            if not cursor:
                break
        if not matches:
            raise ProtocolError("No existing Codex project matches the workspace; no chat created")
        depth = max(match[0] for match in matches)
        project_ids = {identifier for length, identifier in matches if length == depth}
        if len(project_ids) != 1:
            raise ProtocolError("Ambiguous workspace project; no chat created")
        project_id = project_ids.pop()
        thread = client.request("thread/start", {
            "cwd": str(Path(cwd).resolve()), "ephemeral": False,
            "projectId": project_id,
            "approvalPolicy": "never", "sandbox": "read-only",
        })["thread"]
        report["project_id"] = project_id
        report["thread_id"] = thread["id"]
        client.request("thread/name/set", {
            "threadId": thread["id"], "name": "EVE ↔ Nova – Verbindungstest"})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", default="codex")
    parser.add_argument("--socket", help="Existing app-server WebSocket control socket")
    parser.add_argument("--cwd", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--create-test-chat", action="store_true",
                        help="Create an empty persistent test chat; starts no model turn")
    args = parser.parse_args()
    client = None
    try:
        client = SharedServer(args.command, args.socket)
        result = probe(client, args.cwd, args.create_test_chat)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ProtocolError, KeyError, ValueError) as exc:
        if client:
            client.close()
        print(json.dumps({"connected": False, "error": str(exc),
                          "details": client.errors if client else [],
                          "fallback_server_started": False}, ensure_ascii=False, indent=2))
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
