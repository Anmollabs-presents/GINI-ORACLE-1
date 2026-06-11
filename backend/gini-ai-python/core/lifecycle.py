# ============================================================
# GINI-ORACLE-1 — Lifecycle Manager
# core/lifecycle.py
# ============================================================
"""
Manages the complete lifecycle of all Gini services:
  UNINITIALIZED → INITIALIZING → RUNNING → STOPPING → STOPPED

Guarantees:
- Ordered startup (config → logger → registry → services → plugins)
- Ordered shutdown (reverse order)
- Graceful exception handling at every stage
- Signal handling (SIGINT, SIGTERM)
- Status reporting at any point
"""

import asyncio
import signal
import time
from enum import Enum
from typing import List, Callable, Awaitable, Optional
from utils.logger import get_logger
from utils.event_logger import get_event_logger

log = get_logger(__name__)
elog = get_event_logger()


class LifecycleState(str, Enum):
    UNINITIALIZED = "uninitialized"
    INITIALIZING  = "initializing"
    RUNNING       = "running"
    STOPPING      = "stopping"
    STOPPED       = "stopped"
    ERROR         = "error"


class LifecycleHook:
    """A named async hook to be called at a lifecycle stage."""
    def __init__(self, name: str, fn: Callable[[], Awaitable[None]], critical: bool = False):
        self.name = name
        self.fn = fn
        self.critical = critical  # If True, failure halts startup


class LifecycleManager:
    """
    Orchestrates the full startup and shutdown sequence for Gini.

    Usage:
        lm = LifecycleManager()
        lm.add_startup_hook("init_voice", voice_engine.start)
        lm.add_shutdown_hook("stop_voice", voice_engine.stop)
        await lm.startup()
        # ... running ...
        await lm.shutdown()
    """

    def __init__(self):
        self.state = LifecycleState.UNINITIALIZED
        self._startup_hooks: List[LifecycleHook] = []
        self._shutdown_hooks: List[LifecycleHook] = []
        self._shutdown_event = asyncio.Event()
        log.debug("LifecycleManager created")

    # ── Hook Registration ─────────────────────────────────────

    def add_startup_hook(
        self,
        name: str,
        fn: Callable[[], Awaitable[None]],
        critical: bool = False,
    ) -> None:
        """Register a coroutine to run during startup."""
        self._startup_hooks.append(LifecycleHook(name, fn, critical))
        log.debug(f"Startup hook registered: [{name}] critical={critical}")

    def add_shutdown_hook(
        self,
        name: str,
        fn: Callable[[], Awaitable[None]],
    ) -> None:
        """Register a coroutine to run during shutdown."""
        self._shutdown_hooks.append(LifecycleHook(name, fn, critical=False))
        log.debug(f"Shutdown hook registered: [{name}]")

    # ── Lifecycle Execution ───────────────────────────────────

    async def startup(self) -> bool:
        """
        Execute all startup hooks in registration order.
        Returns True if all critical hooks passed, False otherwise.
        """
        self.state = LifecycleState.INITIALIZING
        log.info("⚡ Lifecycle: STARTUP sequence beginning...")
        elog.lifecycle("startup", "begin")

        success = True
        for hook in self._startup_hooks:
            t0 = time.perf_counter()
            try:
                log.info(f"  ▶ [{hook.name}]...")
                await hook.fn()
                elapsed = (time.perf_counter() - t0) * 1_000
                log.info(f"  ✅ [{hook.name}] OK")
                elog.lifecycle("startup_hook", "complete", component=hook.name, elapsed_ms=elapsed)
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1_000
                log.error(f"  ❌ [{hook.name}] FAILED: {e}")
                elog.lifecycle(
                    "startup_hook", "failed",
                    component=hook.name,
                    elapsed_ms=elapsed,
                    error=str(e),
                )
                if hook.critical:
                    log.critical(f"Critical hook [{hook.name}] failed — aborting startup")
                    self.state = LifecycleState.ERROR
                    elog.lifecycle("startup", "failed", error=f"Critical hook [{hook.name}] failed")
                    return False
                success = False  # Non-critical failure, continue

        self.state = LifecycleState.RUNNING
        log.info("🚀 Lifecycle: System is RUNNING")
        elog.lifecycle("startup", "complete")
        return success

    async def shutdown(self) -> None:
        """
        Execute all shutdown hooks in REVERSE order (LIFO).
        Always completes — never raises.
        """
        if self.state == LifecycleState.STOPPED:
            return

        self.state = LifecycleState.STOPPING
        log.info("🛑 Lifecycle: SHUTDOWN sequence beginning...")
        elog.lifecycle("shutdown", "begin")

        for hook in reversed(self._shutdown_hooks):
            t0 = time.perf_counter()
            try:
                log.info(f"  ◀ [{hook.name}]...")
                await hook.fn()
                elapsed = (time.perf_counter() - t0) * 1_000
                log.info(f"  ✅ [{hook.name}] stopped")
                elog.lifecycle("shutdown_hook", "complete", component=hook.name, elapsed_ms=elapsed)
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1_000
                log.error(f"  ❌ [{hook.name}] shutdown error (ignored): {e}")
                elog.lifecycle(
                    "shutdown_hook", "failed",
                    component=hook.name,
                    elapsed_ms=elapsed,
                    error=str(e),
                )

        self.state = LifecycleState.STOPPED
        self._shutdown_event.set()
        log.info("👋 Lifecycle: System STOPPED cleanly")
        elog.lifecycle("shutdown", "complete")

    async def wait_for_shutdown(self) -> None:
        """Block until shutdown() is called (for standalone mode)."""
        await self._shutdown_event.wait()

    def register_signal_handlers(self) -> None:
        """
        Register OS signal handlers for graceful shutdown.
        Handles SIGINT (Ctrl+C) and SIGTERM (kill).
        """
        loop = asyncio.get_event_loop()

        def _handle_signal(sig_name: str):
            log.warning(f"Signal received: {sig_name} — initiating graceful shutdown")
            elog.lifecycle("signal", "received", metadata={"signal": sig_name})
            asyncio.ensure_future(self.shutdown())

        try:
            loop.add_signal_handler(signal.SIGINT,  lambda: _handle_signal("SIGINT"))
            loop.add_signal_handler(signal.SIGTERM, lambda: _handle_signal("SIGTERM"))
            log.debug("Signal handlers registered (SIGINT, SIGTERM)")
        except (NotImplementedError, RuntimeError):
            # Windows doesn't support add_signal_handler
            log.warning("Signal handlers not supported on this platform (Windows?)")

    @property
    def is_running(self) -> bool:
        return self.state == LifecycleState.RUNNING

    @property
    def is_stopped(self) -> bool:
        return self.state == LifecycleState.STOPPED

    def status(self) -> dict:
        return {
            "state": self.state.value,
            "startup_hooks": len(self._startup_hooks),
            "shutdown_hooks": len(self._shutdown_hooks),
        }


__all__ = ["LifecycleManager", "LifecycleState"]
