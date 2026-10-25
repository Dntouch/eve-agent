"""MCP-backed EVE capabilities. No local domain-operation fallback."""
import atexit
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading

from jsonschema import Draft202012Validator

from .mcp_stdio import McpStdioClient


class ProviderMcpCapability:
    def __init__(self, name, root, *, database=None, config_path=None):
        self.name, self.root = name, Path(root).resolve()
        command = [sys.executable, "-m", "eve_agent.provider_mcp_server", name, "--root", str(self.root)]
        if database is not None:
            command.extend(["--database", str(Path(database).resolve())])
        if config_path is not None:
            command.extend(["--config", str(Path(config_path).resolve())])
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(Path(__file__).resolve().parent.parent), env.get("PYTHONPATH")]))
        self.client = McpStdioClient(command, env=env, cwd=str(self.root), protocol_version="2025-11-25")
        self.lock = threading.RLock()
        self.tools = {}
        self._active_conversations = set()
        atexit.register(self.close_all)

    def _request(self, method, parameters):
        self.client.start()
        return self.client.result(self.client.request(method, parameters))

    def minimal_contract(self, conversation_id=None, discoveries=None):
        try:
            return self._contract(conversation_id, discoveries)
        except (RuntimeError, OSError, ValueError) as exc:
            return {"description": f"{self.name} MCP provider unavailable: {exc}",
                    "operations": {}, "error": str(exc)}

    def _contract(self, conversation_id=None, discoveries=None):
        with self.lock:
            page = self._request("tools/list", {})
            tools = list(page["tools"])
            while page.get("nextCursor"):
                page = self._request("tools/list", {"cursor": page["nextCursor"]})
                tools.extend(page["tools"])
            self.tools = {tool["name"]: tool for tool in tools}
            resource = self._request("resources/read", {"uri": f"eve://{self.name}/context",
                "_meta": {"eve/context": {"conversation_id": conversation_id, "discoveries": discoveries or []}}})
            contract = json.loads(resource["contents"][0]["text"])
            if conversation_id:
                if contract.get("active_items"):
                    self._active_conversations.add(conversation_id)
                else:
                    self._active_conversations.discard(conversation_id)
            contract["runtime"] = {"transport": "mcp-stdio", "server": deepcopy(self.client.server["serverInfo"])}
            contract["operations"] = {tool["name"]: {"description": tool.get("description", ""),
                "effect": "read" if tool.get("annotations", {}).get("readOnlyHint") else "write",
                "parameters_schema": deepcopy(tool["inputSchema"])}
                for tool in tools if not tool.get("_meta", {}).get("eve/internal")}
            return contract

    def _call(self, operation, arguments, context):
        with self.lock:
            if operation not in self.tools:
                contract = self.minimal_contract()
                if contract.get("error"):
                    raise RuntimeError(contract["error"])
            if operation not in self.tools:
                raise ValueError("Unknown MCP operation")
            Draft202012Validator(self.tools[operation]["inputSchema"]).validate(arguments)
            native = self._request("tools/call", {"name": operation, "arguments": arguments,
                "_meta": {"eve/context": context}})
            result = native.get("structuredContent")
            if result is None:
                result = json.loads(next(block["text"] for block in native["content"] if block["type"] == "text"))
            if native.get("isError"):
                raise ValueError(f'{result.get("error_class", "MCPError")}: {result.get("message", "MCP tool failed")}')
            return result

    def execute_operation(self, operation, arguments, *, conversation_id=None, discoveries=None, history=None, images=None):
        context = {"conversation_id": conversation_id, "discoveries": discoveries or [],
                   "history": history or [], "images": images or []}
        result = self._call(operation, arguments, context)
        if discoveries is not None:
            discoveries[:] = result.get("discoveries", discoveries)
        if conversation_id and (operation == "get_item" or operation in {
                "create_item", "create_items", "create_list_with_items", "update_item", "complete_item", "reopen_item"}):
            self._active_conversations.add(conversation_id)
        return result

    def has_active_context(self, conversation_id):
        return conversation_id in self._active_conversations

    def attach_mutation_provenance(self, conversation_id, user_message_id):
        return self._call("attach_mutation_provenance", {"conversation_id": conversation_id,
            "user_message_id": user_message_id}, {})["result"]

    def self_descriptions(self):
        if self.name == "work_tasks":
            from .work_tasks import WorkTaskCapability
            return WorkTaskCapability.self_descriptions()
        return []

    def close_all(self):
        with self.lock:
            self.client.close()
            self.tools.clear()
        atexit.unregister(self.close_all)
