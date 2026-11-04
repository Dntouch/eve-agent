"""Turn-local transport authority. Never infer permissions from message text."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

PUBLIC_CAPABILITIES = frozenset({
    "memory", "semantic_learning", "working_memory", "web", "clock", "calculator",
})
_access = ContextVar("eve_transport_access", default=None)


@contextmanager
def transport_access(metadata, *, public=False, allowed_capabilities=None, activity=None):
    allowed = frozenset(allowed_capabilities) if allowed_capabilities is not None else PUBLIC_CAPABILITIES
    token = _access.set({"metadata": deepcopy(metadata), "public": bool(public), "allowed": allowed, "activity": activity})
    try:
        yield
    finally:
        _access.reset(token)


def transport_metadata():
    current = _access.get()
    return deepcopy(current["metadata"]) if current else None


def capability_allowed(name):
    current = _access.get()
    return not current or not current["public"] or name in current["allowed"]


def require_capability(name):
    if not capability_allowed(name):
        raise PermissionError(f"Capability {name} is not permitted in this conversation")


def report_transport_activity(event: dict[str, object]) -> None:
    current = _access.get()
    if current and callable(current.get("activity")):
        current["activity"](deepcopy(event))


def update_transport_metadata(values):
    current = _access.get()
    if current:
        current["metadata"].update(deepcopy(values))
