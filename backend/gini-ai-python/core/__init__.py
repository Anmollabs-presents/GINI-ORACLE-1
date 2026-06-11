# core/__init__.py
# NOTE: bootstrap is intentionally NOT imported here.
# bootstrap.py imports voice.voice_engine which imports core.voice_resilience,
# creating a circular dependency when the voice package __init__ is loaded first.
# Import bootstrap directly where needed: from core.bootstrap import bootstrap
from .assistant import GiniAssistant
from .lifecycle import LifecycleManager, LifecycleState
from .memory import MemoryManager, Session, Turn
from .plugin_manager import PluginManager, GiniPlugin, PluginContext
from .service_registry import ServiceRegistry, ServiceNotFoundError, get_registry

__all__ = [
    "GiniAssistant",
    "LifecycleManager",
    "LifecycleState",
    "MemoryManager",
    "Session",
    "Turn",
    "PluginManager",
    "GiniPlugin",
    "PluginContext",
    "ServiceRegistry",
    "ServiceNotFoundError",
    "get_registry",
]
