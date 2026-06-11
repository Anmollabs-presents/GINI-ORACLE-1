# ============================================================
# GINI-ORACLE-1 — Plugin Manager
# core/plugin_manager.py
# ============================================================
"""
Extensible plugin system for Gini.ai.
Plugins can hook into: message processing, actions, startup, shutdown.

How to create a plugin:
    class MyPlugin(GiniPlugin):
        name = "my_plugin"
        version = "1.0.0"

        async def on_message(self, context: PluginContext) -> Optional[str]:
            # Intercept/modify message processing
            return None  # return None to pass through, or return a string to override response

        async def on_startup(self) -> None:
            pass  # Called when Gini starts

        async def on_shutdown(self) -> None:
            pass  # Called when Gini shuts down
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class PluginContext:
    """Context passed to plugin hooks during message processing."""
    user_id: str
    session_id: str
    message: str
    emotion: str
    metadata: Dict[str, Any]


class GiniPlugin(ABC):
    """
    Base class for all Gini plugins.
    Subclass this to create a plugin.
    """
    name: str = "unnamed_plugin"
    version: str = "1.0.0"
    description: str = ""
    enabled: bool = True

    async def on_startup(self) -> None:
        """Called when Gini starts up."""
        pass

    async def on_shutdown(self) -> None:
        """Called when Gini shuts down."""
        pass

    async def on_message(self, context: PluginContext) -> Optional[str]:
        """
        Called on every incoming message.
        Return a string to override Gini's response.
        Return None to let Gini handle it normally.
        """
        return None

    async def on_action(self, intent: str, payload: dict) -> Optional[dict]:
        """
        Called before every action is routed.
        Return a dict to override the action result.
        Return None to let the action proceed normally.
        """
        return None

    def __repr__(self) -> str:
        return f"Plugin({self.name} v{self.version})"


class PluginManager:
    """
    Manages plugin registration, lifecycle, and hook execution.
    """

    def __init__(self):
        self._plugins: Dict[str, GiniPlugin] = {}  # name → plugin
        log.info("🔌 PluginManager initialized")

    def register(self, plugin: GiniPlugin) -> None:
        """Register a plugin."""
        if not isinstance(plugin, GiniPlugin):
            raise TypeError(f"Plugin must subclass GiniPlugin, got {type(plugin)}")

        if plugin.name in self._plugins:
            log.warning(f"Plugin '{plugin.name}' already registered — skipping")
            return

        self._plugins[plugin.name] = plugin
        log.info(f"  🔌 Plugin registered: [{plugin.name}] v{plugin.version}")

    def unregister(self, name: str) -> None:
        """Remove a plugin by name."""
        if name in self._plugins:
            del self._plugins[name]
            log.info(f"Plugin unregistered: [{name}]")

    def get(self, name: str) -> Optional[GiniPlugin]:
        """Get a plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> List[dict]:
        """List all registered plugins."""
        return [
            {
                "name": p.name,
                "version": p.version,
                "enabled": p.enabled,
                "description": p.description,
            }
            for p in self._plugins.values()
        ]

    async def run_startup_hooks(self) -> None:
        """Call on_startup on all enabled plugins."""
        for plugin in self._active_plugins():
            try:
                await plugin.on_startup()
                log.debug(f"Plugin startup: [{plugin.name}]")
            except Exception as e:
                log.error(f"Plugin [{plugin.name}] startup error: {e}")

    async def run_shutdown_hooks(self) -> None:
        """Call on_shutdown on all enabled plugins."""
        for plugin in self._active_plugins():
            try:
                await plugin.on_shutdown()
                log.debug(f"Plugin shutdown: [{plugin.name}]")
            except Exception as e:
                log.error(f"Plugin [{plugin.name}] shutdown error: {e}")

    async def run_message_hooks(self, context: PluginContext) -> Optional[str]:
        """
        Run all plugin message hooks in order.
        Returns first non-None override, or None if all pass through.
        """
        for plugin in self._active_plugins():
            try:
                result = await plugin.on_message(context)
                if result is not None:
                    log.debug(f"Plugin [{plugin.name}] overrode response")
                    return result
            except Exception as e:
                log.error(f"Plugin [{plugin.name}] message hook error: {e}")
        return None

    async def run_action_hooks(self, intent: str, payload: dict) -> Optional[dict]:
        """
        Run all plugin action hooks.
        Returns first non-None override, or None if all pass through.
        """
        for plugin in self._active_plugins():
            try:
                result = await plugin.on_action(intent, payload)
                if result is not None:
                    return result
            except Exception as e:
                log.error(f"Plugin [{plugin.name}] action hook error: {e}")
        return None

    def _active_plugins(self) -> List[GiniPlugin]:
        """Return only enabled plugins."""
        return [p for p in self._plugins.values() if p.enabled]

    @property
    def count(self) -> int:
        return len(self._plugins)


__all__ = ["PluginManager", "GiniPlugin", "PluginContext"]
