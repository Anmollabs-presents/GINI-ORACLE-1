# ============================================================
# GINI-ORACLE-1 — Service Registry (Dependency Container)
# core/service_registry.py
# ============================================================
"""
Central service container for Gini.ai.
All services (voice, actions, memory, plugins) register here.
Any module can resolve a service by name — no tight coupling.

Usage:
    registry = ServiceRegistry()
    registry.register("voice", VoiceEngine())
    engine = registry.resolve("voice")
"""

from typing import Any, Dict, Optional, Type
from utils.logger import get_logger

log = get_logger(__name__)


class ServiceNotFoundError(Exception):
    """Raised when resolving an unregistered service."""
    pass


class ServiceRegistry:
    """
    Lightweight service container.
    Supports: register, resolve, has, unregister, list_services.
    Thread-safe for read operations.
    """

    def __init__(self):
        self._services: Dict[str, Any] = {}
        self._factories: Dict[str, Any] = {}  # lazy-init factories
        log.debug("ServiceRegistry initialized")

    def register(self, name: str, instance: Any, overwrite: bool = False) -> None:
        """
        Register a live service instance.

        Args:
            name: Service identifier key
            instance: The service object
            overwrite: Allow replacing existing service
        """
        if name in self._services and not overwrite:
            log.warning(f"Service '{name}' already registered. Use overwrite=True to replace.")
            return
        self._services[name] = instance
        log.info(f"  📦 Service registered: [{name}] → {type(instance).__name__}")

    def register_factory(self, name: str, factory: callable) -> None:
        """
        Register a lazy factory — instantiated only when first resolved.

        Args:
            name: Service identifier key
            factory: A callable that returns the service instance
        """
        self._factories[name] = factory
        log.debug(f"Factory registered: [{name}]")

    def resolve(self, name: str) -> Any:
        """
        Resolve a registered service by name.
        If a factory is registered, it instantiates and caches it.

        Raises:
            ServiceNotFoundError if service not found
        """
        if name in self._services:
            return self._services[name]

        # Try lazy factory
        if name in self._factories:
            log.debug(f"Lazy-initializing service: [{name}]")
            instance = self._factories[name]()
            self._services[name] = instance
            del self._factories[name]
            return instance

        raise ServiceNotFoundError(
            f"Service '{name}' is not registered. "
            f"Available: {list(self._services.keys())}"
        )

    def resolve_optional(self, name: str) -> Optional[Any]:
        """Resolve a service, returns None if not found instead of raising."""
        try:
            return self.resolve(name)
        except ServiceNotFoundError:
            return None

    def has(self, name: str) -> bool:
        """Check if a service is registered (live or factory)."""
        return name in self._services or name in self._factories

    def unregister(self, name: str) -> None:
        """Remove a service from the registry."""
        removed = False
        if name in self._services:
            del self._services[name]
            removed = True
        if name in self._factories:
            del self._factories[name]
            removed = True
        if removed:
            log.info(f"Service unregistered: [{name}]")
        else:
            log.warning(f"Tried to unregister unknown service: [{name}]")

    def list_services(self) -> Dict[str, str]:
        """Return all registered services with their types."""
        result = {name: type(inst).__name__ for name, inst in self._services.items()}
        result.update({name: f"<factory:{name}>" for name in self._factories})
        return result

    def __repr__(self) -> str:
        return f"ServiceRegistry(services={list(self._services.keys())}, factories={list(self._factories.keys())})"


# ── Global singleton registry ────────────────────────────────
_global_registry: Optional[ServiceRegistry] = None


def get_registry() -> ServiceRegistry:
    """Returns the global singleton ServiceRegistry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ServiceRegistry()
    return _global_registry


__all__ = ["ServiceRegistry", "ServiceNotFoundError", "get_registry"]
