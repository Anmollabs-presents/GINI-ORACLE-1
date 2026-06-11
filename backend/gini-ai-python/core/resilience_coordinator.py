# ============================================================
# GINI-ORACLE-1 — Resilience Coordinator
# core/resilience_coordinator.py
# ============================================================
"""
Master coordinator for all resilience operations.
Integrates all failure handling and recovery mechanisms.

Responsibilities:
  1. Initialize all resilience managers on startup
  2. Run comprehensive health checks
  3. Coordinate recovery flows across subsystems
  4. Provide unified error handling interface
  5. Generate health/status reports
  6. Trigger self-healing procedures

Failure Modes Handled:
  ✅ Microphone failure
  ✅ Missing dependencies
  ✅ App not found
  ✅ Invalid command
  ✅ Browser failure
  ✅ TTS crash
  ✅ STT timeout
  ✅ Backend disconnect
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

from utils.logger import get_logger
from core.resilience import (
    FailureMode, RecoveryStrategy, FailureContext,
    get_recovery_manager, RecoveryManager
)
from core.voice_resilience import get_voice_resilience, VoiceResilienceManager
from core.app_resilience import get_app_resilience, AppResilienceManager
from core.web_resilience import get_web_resilience, get_backend_resilience
from core.web_resilience import WebResilienceManager, BackendResilienceManager
from core.dependency_validator import get_dependency_validator, DependencyValidator

log = get_logger(__name__)


@dataclass
class SystemHealth:
    """Overall system health status."""
    is_healthy: bool
    timestamp: datetime = field(default_factory=datetime.now)
    subsystems: Dict[str, Dict] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "healthy": self.is_healthy,
            "timestamp": self.timestamp.isoformat(),
            "subsystems": self.subsystems,
            "failures": self.failures,
            "warnings": self.warnings,
            "recommendations": self.recommendations,
        }


class ResilienceCoordinator:
    """
    Master coordinator for resilience operations.
    Centralizes error handling and recovery across entire system.
    """

    def __init__(self):
        self.recovery_manager = get_recovery_manager()
        self.voice_resilience = get_voice_resilience()
        self.app_resilience = get_app_resilience()
        self.web_resilience = get_web_resilience()
        self.backend_resilience = get_backend_resilience()
        self.dependency_validator = get_dependency_validator()

        self.initialized = False
        self.health = SystemHealth(is_healthy=False)
        self.startup_time: Optional[datetime] = None

        log.info("🛡️ ResilienceCoordinator created")

    # ── Initialization ────────────────────────────────────────

    async def initialize(self) -> bool:
        """Initialize all resilience systems at startup."""
        log.info("🚀 Initializing resilience layer...")

        try:
            # Run dependency checks
            log.info("  ▶ Checking dependencies...")
            await self.dependency_validator.check_all_dependencies()

            # Run health checks
            log.info("  ▶ Running health checks...")
            self.health = await self.run_health_checks()

            if not self.health.is_healthy:
                log.warning(f"⚠️  System initialized with issues: {self.health.failures}")
            else:
                log.info("✅ Resilience layer fully initialized")

            self.initialized = True
            self.startup_time = datetime.now()
            return True

        except Exception as e:
            log.error(f"❌ Resilience initialization failed: {e}")
            return False

    # ── Health Checks ─────────────────────────────────────────

    async def run_health_checks(self) -> SystemHealth:
        """Run comprehensive health checks on all subsystems."""
        log.info("🏥 Running comprehensive health checks...")

        health = SystemHealth(is_healthy=True)

        # Check dependencies
        dep_report = self.dependency_validator.get_report()
        health.subsystems["dependencies"] = dep_report
        if not dep_report["healthy"]:
            health.is_healthy = False
            health.failures.extend([
                f"Missing: {check['name']}"
                for check in dep_report["checks"]
                if check["status"] == "missing"
            ])

        # Check voice system
        voice_status = self.voice_resilience.get_status()
        health.subsystems["voice"] = voice_status
        for circuit_name, circuit_info in voice_status.get("circuits", {}).items():
            if circuit_info["state"] == "open":
                health.warnings.append(f"Voice subsystem {circuit_name} circuit is OPEN")

        # Check app system
        app_status = self.app_resilience.get_status()
        health.subsystems["app"] = app_status

        # Check web system
        web_status = self.web_resilience.get_status()
        health.subsystems["web"] = web_status

        # Check backend system
        backend_status = self.backend_resilience.get_status()
        health.subsystems["backend"] = backend_status

        # Add recommendations
        recommendations = await self.dependency_validator.get_recommendations()
        health.recommendations.extend(recommendations)

        log.info(
            f"🏥 Health check complete: "
            f"{'✅ Healthy' if health.is_healthy else '⚠️  Issues detected'}"
        )

        return health

    # ── Unified Error Handling ────────────────────────────────

    async def handle_error(
        self,
        failure_mode: FailureMode,
        error_message: str,
        context: Optional[Dict] = None,
    ) -> dict:
        """
        Central error handler for all failure modes.
        Routes to appropriate recovery manager.
        """
        log.error(f"🚨 Handling {failure_mode.value}: {error_message}")

        context = context or {}
        recovery_action = None

        try:
            # Route to appropriate resilience manager
            if failure_mode == FailureMode.MISSING_DEPENDENCY:
                recovery_action = await self.handle_missing_dependency(
                    context.get("dependency", "unknown"),
                    context.get("feature", "core"),
                )

            elif failure_mode == FailureMode.MIC_FAILURE:
                recovery_action = await self.voice_resilience.handle_mic_failure(
                    error_message,
                    context.get("available_devices"),
                )

            elif failure_mode == FailureMode.STT_TIMEOUT:
                recovery_action = await self.voice_resilience.handle_stt_timeout(
                    context.get("current_timeout", 15.0),
                )

            elif failure_mode == FailureMode.TTS_CRASH:
                recovery_action = await self.voice_resilience.handle_tts_crash(error_message)

            elif failure_mode == FailureMode.APP_NOT_FOUND:
                recovery_action = await self.app_resilience.handle_app_not_found(
                    context.get("app_name", "unknown")
                )

            elif failure_mode == FailureMode.INVALID_COMMAND:
                recovery_action = await self.app_resilience.handle_invalid_command(
                    context.get("command", ""),
                    error_message,
                )

            elif failure_mode == FailureMode.BROWSER_FAILURE:
                recovery_action = await self.web_resilience.handle_browser_crash(
                    context.get("browser_name", "unknown")
                )

            elif failure_mode == FailureMode.BACKEND_DISCONNECT:
                result = await self.backend_resilience.handle_backend_disconnect(
                    error_message
                )
                recovery_action = result

            else:
                log.warning(f"Unhandled failure mode: {failure_mode}")

            # Record failure
            failure_context = FailureContext(
                mode=failure_mode,
                message=error_message,
                service=context.get("service", "unknown"),
                recovery_strategy=RecoveryStrategy.RETRY if recovery_action else RecoveryStrategy.ABORT,
                metadata=context,
            )
            self.recovery_manager.record_failure(failure_context)

            # Return recovery action
            return self._recovery_to_dict(
                failure_mode=failure_mode,
                error_message=error_message,
                recovery_action=recovery_action,
            )

        except Exception as e:
            log.error(f"Error in error handler: {e}")
            return {
                "fallback_mode": "abort",
                "message": "An error occurred during recovery. Please try again.",
                "can_retry": True,
            }

    async def handle_missing_dependency(self, dependency: str, feature: str = "core") -> dict:
        """Handle missing dependency by degrading the affected feature."""
        dependency = dependency or "unknown"
        feature = feature or "core"
        recommendations = await self.dependency_validator.get_recommendations()
        matching = [
            rec for rec in recommendations
            if dependency.lower() in rec.lower()
        ]
        return {
            "status": "degraded",
            "fallback_mode": "feature_disabled",
            "message": (
                f"{feature} is temporarily disabled because '{dependency}' "
                "is missing."
            ),
            "suggestions": matching or [f"Install missing dependency: {dependency}"],
            "can_retry": True,
            "is_critical": feature == "core",
        }

    def _recovery_to_dict(
        self,
        failure_mode: FailureMode,
        error_message: str,
        recovery_action,
    ) -> dict:
        """Normalize manager-specific recovery objects into one API shape."""
        if recovery_action is None:
            return {
                "status": "error",
                "failure_mode": failure_mode.value,
                "fallback_mode": "abort",
                "message": error_message,
                "can_retry": False,
            }

        if hasattr(recovery_action, "to_dict"):
            payload = recovery_action.to_dict()
        elif isinstance(recovery_action, dict):
            payload = dict(recovery_action)
        else:
            payload = {
                "fallback_mode": getattr(recovery_action, "fallback_mode", "abort"),
                "message": getattr(recovery_action, "user_message", error_message),
                "can_retry": getattr(recovery_action, "can_retry", False),
            }

        payload.setdefault("status", "degraded")
        payload.setdefault("failure_mode", failure_mode.value)
        payload.setdefault("message", error_message)
        payload.setdefault("can_retry", False)
        return payload

    # ── Self-Healing ──────────────────────────────────────────

    async def trigger_self_healing(self) -> dict:
        """Attempt to self-heal all subsystems."""
        log.info("🏥 Triggering system-wide self-healing...")

        results = {
            "voice": await self.voice_resilience.self_heal(),
            "app": await self.app_resilience.self_heal(),
            "web": await self.web_resilience.self_heal(),
            "overall_status": "partial_healing",
        }

        # Check if we recovered
        new_health = await self.run_health_checks()
        if new_health.is_healthy and self.health.is_healthy != new_health.is_healthy:
            results["overall_status"] = "recovered"
            log.info("✅ System self-healing successful!")

        self.health = new_health
        return results

    # ── Status and Reporting ──────────────────────────────────

    def get_status(self) -> dict:
        """Get comprehensive system status."""
        uptime_sec = None
        if self.startup_time:
            uptime_sec = (datetime.now() - self.startup_time).total_seconds()

        return {
            "initialized": self.initialized,
            "healthy": self.health.is_healthy,
            "uptime_seconds": uptime_sec,
            "subsystems": self.health.subsystems,
            "failure_report": self.recovery_manager.get_failure_report(),
            "warnings": self.health.warnings,
            "recommendations": self.health.recommendations,
        }

    def get_health(self) -> dict:
        """Get detailed health report."""
        return self.health.to_dict()

    async def get_diagnostics(self) -> dict:
        """Get full diagnostic report."""
        return {
            "health": self.health.to_dict(),
            "dependency_report": self.dependency_validator.get_report(),
            "recovery_circuits": {
                name: cb.status()
                for name, cb in self.recovery_manager.circuits.items()
            },
            "recent_failures": self.recovery_manager.failure_history[-20:],
        }

    # ── Integration Helpers ───────────────────────────────────

    async def validate_before_operation(
        self,
        operation_type: str,
        context: Optional[Dict] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        Validate system is ready for an operation.
        Returns (can_proceed, error_message).
        """
        context = context or {}

        if operation_type == "voice_capture":
            if not self.voice_resilience.mic_available:
                return False, "Microphone not available"

        elif operation_type == "app_launch":
            app_name = context.get("app_name")
            if app_name:
                valid, error = await self.app_resilience.validate_app_name(app_name)
                if not valid:
                    return False, error

        elif operation_type == "web_access":
            url = context.get("url")
            if url:
                valid, error = self.web_resilience.validate_url(url)
                if not valid:
                    return False, error

        return True, None

    # ── Request Queueing (for offline resilience) ────────────

    def queue_request_for_retry(self, request: dict) -> bool:
        """Queue a request for retry when services recover."""
        log.info(f"📋 Queueing request: {request.get('operation', 'unknown')}")
        # In production, persist to database or message queue
        return True


# ── Global instance ──────────────────────────────────────

_coordinator: Optional[ResilienceCoordinator] = None


def get_resilience_coordinator() -> ResilienceCoordinator:
    """Get or create global resilience coordinator."""
    global _coordinator
    if _coordinator is None:
        _coordinator = ResilienceCoordinator()
    return _coordinator


__all__ = [
    "ResilienceCoordinator",
    "SystemHealth",
    "get_resilience_coordinator",
]
