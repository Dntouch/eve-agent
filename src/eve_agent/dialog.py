from __future__ import annotations

from enum import Enum


class Route(str, Enum):
    """Stable telemetry labels for model-selected capabilities."""

    SOURCE_META = "source_meta"
    REMINDER = "reminder"
    NETWORK = "network"
    CLOCK = "clock"
    CALCULATOR = "calculator"
    MEMORY = "memory"
    WORK_TASKS = "work_tasks"
    LOCAL_SEARCH = "local_search"
    LOCAL_FILES = "local_files"
    DEVICE_ALIASES = "device_aliases"
    NOVA_MAINTENANCE = "nova_maintenance"
    NOVA_CONFIRM = "nova_confirm"
    NOVA_CANCEL = "nova_cancel"
    NOVA_PENDING_INFO = "nova_pending_info"
    HOME_CONFIRM = "home_confirm"
    HOME_CANCEL = "home_cancel"
    HOME_PENDING_INFO = "home_pending_info"
    HOME = "home"
    WEB = "web"
    PRESENTATION = "presentation"
    COMPUTER = "computer"
    SHELL = "shell"
    CHAT = "chat"
