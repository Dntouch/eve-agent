"""Explicit wire schemas shared by MCP discovery and execution validation."""
from copy import deepcopy


def obj(properties=None, required=(), **constraints):
    return {"type": "object", "properties": properties or {},
            "additionalProperties": False, **({"required": list(required)} if required else {}),
            **constraints}


def text(description="", **constraints):
    return {"type": "string", **({"description": description} if description else {}), **constraints}


LIST = {"list_id": text("UUID from the published lists"),
        "list_name": text("Exact name from the published lists; alternative to list_id")}
LIST_REQUIRED = {"anyOf": [{"required": ["list_id"]}, {"required": ["list_name"]}]}
STATUS = {"type": "string", "enum": ["open", "completed"]}
ITEMS = {"type": "array", "minItems": 1, "maxItems": 25,
         "items": obj({"title": text(minLength=1), "description": text()}, ["title"])}
TARGET = {"item_id": text("UUID from search_items or the active task context"),
          "target_origin": {"type": "string", "enum": ["current_discovery", "active_context"]},
          "target_resolution": {"type": "string", "enum": ["exact"]}}

WORK_TASK_SCHEMAS = {
    "create_list": obj({"name": text(minLength=1), "description": text()}, ["name"]),
    "create_list_with_items": obj({"name": text(minLength=1), "description": text(), "items": ITEMS}, ["name", "items"]),
    "list_lists": obj(),
    "delete_list": obj(LIST, **LIST_REQUIRED),
    "create_item": obj({**LIST, "title": text(minLength=1), "description": text()}, ["title"], **LIST_REQUIRED),
    "create_items": obj({**LIST, "items": ITEMS}, ["items"], **LIST_REQUIRED),
    "list_items": obj({**LIST, "status": STATUS}),
    "search_items": obj({"query": text(minLength=1), "status": STATUS}, ["query"]),
    "get_item": obj({"item_id": TARGET["item_id"]}, ["item_id"]),
    "update_item": obj({**TARGET, "changes": obj({
        "title": text(), "description": text(), "list_id": text(), "status": STATUS,
        "metadata": {"type": "object", "additionalProperties": True}}),
        "description_message_id": text("Published assistant-message UUID; its exact text replaces description")},
        ["item_id", "changes"]),
    "add_context_link": obj({**TARGET,
        "scope": {"type": "string", "enum": ["conversation", "current_turn", "last_messages", "last_turns"]},
        "count": {"type": "integer", "minimum": 1}, "label": text()}, ["item_id", "scope"],
        allOf=[{"if": {"properties": {"scope": {"enum": ["last_messages", "last_turns"]}}},
                "then": {"required": ["count"]}}]),
    **{name: obj(TARGET, ["item_id"]) for name in ["complete_item", "reopen_item", "delete_item"]},
}

NOVA_OPERATIONS = {
    "run": {"description": "Ask Nova/Codex to diagnose or develop EVE in a project snapshot. Returns the actual report; does not restart EVE.",
            "effect": "write", "parameters_schema": obj({"instruction": text(minLength=1),
                "level": {"type": "string", "enum": ["diagnosis", "development"]}}, ["instruction", "level"])},
    "pending_info": {"description": "Read the pending Nova activation proposal.", "effect": "read", "parameters_schema": obj()},
    **{name: {"description": description, "effect": "write",
              "parameters_schema": obj({"job_id": text("Exact published pending job ID")}, ["job_id"])}
       for name, description in [("activate_pending", "Activate the published, tested Nova proposal."),
                                 ("cancel_pending", "Discard the published Nova proposal.")]},
}


def work_task_operations(descriptions):
    return {name: {"description": descriptions[name],
                   "effect": "read" if name in {"list_lists", "list_items", "search_items", "get_item"} else "write",
                   "parameters_schema": deepcopy(schema)} for name, schema in WORK_TASK_SCHEMAS.items()}
