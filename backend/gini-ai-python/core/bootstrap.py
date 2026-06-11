# ============================================================
# GINI-ORACLE-1 — Bootstrap Sequence
# core/bootstrap.py
# ============================================================
"""
The bootstrap module wires all Gini components together
in the correct order and registers them into the ServiceRegistry.

Startup order:
  1. Config (already loaded via import)
  2. Logger (already initialized via import)
  3. MemoryManager
  4. ActionRouter
  5. VoiceEngine
  6. PluginManager + plugin hooks
  7. GiniAssistant (receives all above via registry)
  8. LifecycleManager (registers shutdown cleanup)

This module is the single source of truth for
how the system is assembled — not scattered across files.
"""

from config.settings import settings
from utils.logger import get_logger
from utils.health import run_health_checks
from utils.event_logger import get_event_logger

from core.service_registry import ServiceRegistry, get_registry
from core.lifecycle import LifecycleManager
from core.memory import MemoryManager
from core.plugin_manager import PluginManager
from core.assistant import GiniAssistant
from voice.voice_engine import VoiceEngine

log = get_logger(__name__)
elog = get_event_logger()


async def _noop():
    """No-op coroutine for optional/placeholder hooks."""
    pass


async def bootstrap() -> tuple[GiniAssistant, LifecycleManager]:
    """
    Full bootstrap sequence for Gini.ai.

    Returns:
        (GiniAssistant, LifecycleManager) — ready to use

    Raises:
        RuntimeError if a critical startup step fails
    """
    import time
    _boot_start = time.perf_counter()

    log.info("=" * 60)
    log.info(f"  🌟 Bootstrapping {settings.app_name} v{settings.app_version}")
    log.info(f"  🌍 Environment : {settings.app_env}")
    log.info("=" * 60)
    elog.lifecycle(
        "bootstrap", "begin",
        metadata={
            "app_name": settings.app_name,
            "version":  settings.app_version,
            "env":      settings.app_env,
        },
    )

    # ── Step 1: Health Checks ─────────────────────────────────
    log.info("▶ Running pre-boot health checks...")
    elog.lifecycle("bootstrap", "health_checks", component="pre_boot")
    report = run_health_checks()
    if not report.is_healthy:
        failed_names = [f.name for f in report.failed]
        log.warning(f"⚠️  Health issues detected: {failed_names}")
        elog.warning(
            "health_check_failed",
            f"Pre-boot health issues: {failed_names}",
            service="bootstrap",
            context={"failed": failed_names},
        )

    # ── Step 2: Service Registry ──────────────────────────────
    log.info("▶ Initializing service registry...")
    elog.lifecycle("bootstrap", "service_registry", component="ServiceRegistry")
    registry: ServiceRegistry = get_registry()

    # ── Step 3: Core Services ─────────────────────────────────
    log.info("▶ Initializing core services...")
    elog.lifecycle("bootstrap", "core_services", component="memory,action_router,voice,plugins")

    memory_manager = MemoryManager()
    registry.register("memory", memory_manager)

    # Lazy import to avoid circular dependency
    from actions.action_router import ActionRouter
    action_router = ActionRouter()
    registry.register("action_router", action_router)

    voice_engine = VoiceEngine()
    registry.register("voice", voice_engine)

    plugin_manager = PluginManager()
    registry.register("plugins", plugin_manager)

    # ── Step 4: Assistant (receives registry) ─────────────────
    log.info("▶ Initializing GiniAssistant...")
    elog.lifecycle("bootstrap", "assistant_init", component="GiniAssistant")
    assistant = GiniAssistant(registry=registry)
    registry.register("assistant", assistant)

    # ── Step 5: Lifecycle Manager ─────────────────────────────
    log.info("▶ Configuring lifecycle manager...")
    elog.lifecycle("bootstrap", "lifecycle_config", component="LifecycleManager")
    lifecycle = LifecycleManager()

    # Startup hooks
    lifecycle.add_startup_hook(
        "plugin_startup",
        plugin_manager.run_startup_hooks,
        critical=False,
    )
    lifecycle.add_startup_hook(
        "assistant_ready",
        assistant.on_startup,
        critical=True,
    )

    # Shutdown hooks (registered in reverse-teardown order)
    lifecycle.add_shutdown_hook("assistant_shutdown", assistant.on_shutdown)
    lifecycle.add_shutdown_hook("plugin_shutdown", plugin_manager.run_shutdown_hooks)
    lifecycle.add_shutdown_hook("voice_shutdown", _noop)       # Phase 2: voice_engine.stop()

    # Register signal handlers (SIGINT / SIGTERM)
    lifecycle.register_signal_handlers()

    # ── Step 6: Execute startup hooks ─────────────────────────
    log.info("▶ Running startup lifecycle hooks...")
    elog.lifecycle("bootstrap", "startup_hooks", component="LifecycleManager")
    success = await lifecycle.startup()
    if not success:
        elog.failure(
            "bootstrap_critical_failure",
            "Critical lifecycle startup hook failed",
            service="bootstrap",
            critical=True,
        )
        raise RuntimeError("Critical lifecycle startup hook failed — see logs above")

    # ── Done ──────────────────────────────────────────────────
    elapsed_ms = (time.perf_counter() - _boot_start) * 1_000
    log.info("=" * 60)
    log.info(f"  ✅ {settings.app_name} bootstrap complete")
    log.info(f"  📦 Services: {list(registry.list_services().keys())}")
    log.info(f"  🔌 Plugins : {plugin_manager.count}")
    log.info("=" * 60)

    elog.lifecycle(
        "bootstrap", "complete",
        elapsed_ms=elapsed_ms,
        metadata={
            "services":  list(registry.list_services().keys()),
            "plugins":   plugin_manager.count,
        },
    )

    return assistant, lifecycle


__all__ = ["bootstrap"]
