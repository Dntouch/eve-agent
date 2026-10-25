"""Per-job MCP mailbox. The EVE process owns and executes every request."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, ensure_ascii=False)
    os.replace(temporary, path)


TOOL = {
    "name": "eve_execute_snapshot",
    "description": "Übergibt den vollständigen aktuellen Auftrag an EVEs isolierten Worker. Liefert dessen geprüften Bericht; kein Deployment.",
    "inputSchema": {"type": "object", "additionalProperties": False,
                    "properties": {"instruction": {"type": "string", "minLength": 1, "maxLength": 64000}},
                    "required": ["instruction"]},
    "annotations": {"readOnlyHint": False, "destructiveHint": False,
                    "idempotentHint": False, "openWorldHint": False},
}


def dispatch(directory, method, params, timeout=900):
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", "2025-11-25"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "eve-isolated-snapshot", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": [TOOL]}
    if method != "tools/call":
        raise LookupError("Unknown MCP method")
    arguments = params.get("arguments", {})
    if (params.get("name") != TOOL["name"] or not isinstance(arguments, dict)
            or set(arguments) != {"instruction"} or not isinstance(arguments["instruction"], str)
            or not arguments["instruction"].strip() or len(arguments["instruction"]) > 64000):
        raise ValueError("Invalid isolated execution request")
    if not (directory / "active").is_file():
        raise RuntimeError("Dieser EVE-Aufruf ist abgeschlossen. Neue Arbeit bitte über EVE beauftragen.")
    identifier = uuid.uuid4().hex
    write_json(directory / f"{identifier}.request.json", arguments)
    response_path = directory / f"{identifier}.response.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if response_path.is_file():
            response = json.loads(response_path.read_text())
            return {"content": [{"type": "text", "text": json.dumps(response, ensure_ascii=False)}],
                    "structuredContent": response, "isError": not response["success"]}
        if not (directory / "active").is_file():
            raise RuntimeError("EVE-Aufruf unterbrochen oder beendet; keine Aktivierung")
        time.sleep(0.05)
    raise TimeoutError("Timeout beim isolierten EVE-Worker")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    for line in sys.stdin:
        message = json.loads(line)
        if "id" not in message:
            continue
        try:
            result = dispatch(args.directory, message["method"], message.get("params", {}))
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except Exception as exc:
            if message.get("method") == "tools/call":
                result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
                reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
            else:
                reply = {"jsonrpc": "2.0", "id": message["id"], "error": {
                    "code": -32601 if isinstance(exc, LookupError) else -32602, "message": str(exc)}}
        print(json.dumps(reply, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
