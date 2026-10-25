"""EVE work-task and Nova MCP servers (newline-delimited JSON-RPC over stdio).

Only domain services live here. The model-facing client uses tools/list schemas
unchanged, and execution validates those same schemas before touching a service.
"""
import argparse
from copy import deepcopy
import json
import sqlite3
import sys

from jsonschema import Draft202012Validator, ValidationError

from .provider_schemas import obj, text


class ProviderMcpServer:
    def __init__(self, name, backend):
        self.name, self.backend = name, backend
        self.initialized = False
        self.protocol = "2025-11-25"
        self.discoveries = {}

    @property
    def uri(self):
        return f"eve://{self.name}/context"

    def tools(self):
        contract = self.backend.minimal_contract()
        tools = [{"name": name, "description": operation["description"],
                  "inputSchema": deepcopy(operation["parameters_schema"]),
                  "annotations": {"readOnlyHint": operation["effect"] == "read"}}
                 for name, operation in contract["operations"].items()]
        if self.name == "work_tasks":
            tools.append({"name": "attach_mutation_provenance",
                          "description": "Runtime bookkeeping: link the persisted triggering message to the last task mutation.",
                          "inputSchema": obj({"conversation_id": text(), "user_message_id": text()},
                                             ["conversation_id", "user_message_id"]),
                          "_meta": {"eve/internal": True}})
        return tools

    def context(self, context):
        if self.name == "work_tasks":
            result = self.backend.minimal_contract(context.get("conversation_id"), context.get("discoveries"))
        else:
            result = self.backend.minimal_contract()
        result.pop("operations", None)
        return result

    def dispatch(self, method, params):
        if method == "initialize":
            requested = params.get("protocolVersion")
            self.protocol = requested if requested in {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"} else "2025-11-25"
            self.initialized = True
            return {"protocolVersion": self.protocol, "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": f"eve-{self.name}", "version": "1.0"}}
        if method == "ping":
            return {}
        if not self.initialized:
            raise ValueError("MCP initialize is required")
        context = (params.get("_meta") or {}).get("eve/context") or {}
        if not isinstance(context, dict):
            raise ValueError("MCP EVE context must be an object")
        if self.name == "work_tasks":
            key = context.get("conversation_id")
            if "discoveries" in context:
                self.discoveries[key] = context["discoveries"]
            context["discoveries"] = self.discoveries.setdefault(key, [])
        if method == "tools/list":
            return {"tools": self.tools()}
        if method == "resources/list":
            return {"resources": [{"uri": self.uri, "name": f"{self.name} context", "mimeType": "application/json"}]}
        if method == "resources/read":
            if params.get("uri") != self.uri:
                raise ValueError("Unknown MCP resource URI")
            return {"contents": [{"uri": self.uri, "mimeType": "application/json",
                                  "text": json.dumps(self.context(context), ensure_ascii=False)}]}
        if method != "tools/call":
            raise LookupError("Unknown MCP method")
        tool = next((t for t in self.tools() if t["name"] == params.get("name")), None)
        if tool is None:
            raise ValueError("Unknown MCP tool")
        try:
            arguments = params.get("arguments", {})
            Draft202012Validator(tool["inputSchema"]).validate(arguments)
            if tool["name"] == "attach_mutation_provenance":
                result = {"result": self.backend.attach_mutation_provenance(**arguments)}
            elif self.name == "work_tasks":
                result = self.backend.execute_operation(tool["name"], arguments,
                    conversation_id=context.get("conversation_id"), discoveries=context.get("discoveries", []))
            else:
                result = {"result": self.backend.execute_operation(tool["name"], arguments,
                    history=context.get("history"), images=context.get("images"))}
                if tool["name"] == "run":
                    result["report"] = deepcopy(self.backend.last_result or {})
                    if getattr(self.backend, "last_chat_id", None):
                        result["chat"] = {"thread_id": self.backend.last_chat_id,
                                          "job_id": self.backend.last_job_id,
                                          "transport": "shared_chat"}
                    if result["report"].get("status") == "failed":
                        result.update(status="error", error_class="NovaMaintenanceError", message=result["result"])
                        return self.tool_result(result, error=True)
            return self.tool_result(result)
        except (ValueError, KeyError, TypeError, RuntimeError, OSError, sqlite3.Error, ValidationError) as exc:
            return self.tool_result({"status": "error", "error_class": type(exc).__name__, "message": exc.message if isinstance(exc, ValidationError) else str(exc)}, error=True)

    @staticmethod
    def tool_result(result, *, error=False):
        return {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result, "isError": error}

    def serve(self, source, target):
        for line in source:
            request = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                    raise ValueError("Invalid JSON-RPC request")
                if "id" not in request:
                    continue
                result = self.dispatch(request.get("method"), request.get("params") or {})
                response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
            except Exception as exc:
                response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                            "error": {"code": -32700 if isinstance(exc, json.JSONDecodeError) else
                                      -32601 if isinstance(exc, LookupError) else -32602,
                                      "message": str(exc)}}
            target.write(json.dumps(response, ensure_ascii=False) + "\n")
            target.flush()


def main():
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=["work_tasks", "nova"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.provider == "work_tasks":
        from .storage import EveDatabase
        from .work_tasks import WorkTaskCapability, WorkTaskStore
        backend = WorkTaskCapability(WorkTaskStore(EveDatabase(args.database or args.root / "data/eve.db")), None)
    else:
        from .config import default_config_path, load_config
        from .diagnostics import DiagnosticJournal
        from .home_assistant import HomeAssistant
        from .nova_maintenance import NovaMaintenance
        _, config = load_config(args.config or default_config_path(args.root))
        ha_config = config.get("home_assistant", {})
        home = HomeAssistant(ha_config, args.root) if ha_config.get("enabled") else None
        backend = NovaMaintenance(args.root, config["nova_maintenance"],
            DiagnosticJournal(config["paths"]["runtime"]), system_config=config,
            system_snapshot_provider=home.diagnostic_snapshot if home else None)
    ProviderMcpServer(args.provider, backend).serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    main()
