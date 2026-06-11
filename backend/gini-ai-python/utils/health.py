# ============================================================
# GINI-ORACLE-1 — Startup Health Check System
# utils/health.py
# ============================================================

from dataclasses import dataclass, field
from typing import List
from utils.logger import get_logger
from config.settings import settings

log = get_logger(__name__)


@dataclass
class HealthCheckResult:
    name: str
    status: bool
    message: str


@dataclass
class SystemHealthReport:
    passed: List[HealthCheckResult] = field(default_factory=list)
    failed: List[HealthCheckResult] = field(default_factory=list)

    @property
    def is_healthy(self) -> bool:
        return len(self.failed) == 0

    def summary(self) -> str:
        total = len(self.passed) + len(self.failed)
        return (
            f"Health Check: {len(self.passed)}/{total} passed | "
            f"{'✅ System Healthy' if self.is_healthy else '❌ Issues Found'}"
        )


def check_environment() -> HealthCheckResult:
    """Validate critical environment variables."""
    issues = []
    if settings.secret_key == "change_this_in_production" and settings.app_env == "production":
        issues.append("SECRET_KEY must be changed in production")

    if issues:
        return HealthCheckResult("Environment", False, " | ".join(issues))
    return HealthCheckResult("Environment", True, "Environment config OK (offline-first mode)")


def check_modules() -> HealthCheckResult:
    """Check all Gini modules are importable."""
    try:
        # Use direct module imports to avoid triggering core/__init__.py
        # which had a circular dependency chain through bootstrap
        import importlib
        importlib.import_module("core.assistant")
        importlib.import_module("voice.voice_engine")
        importlib.import_module("actions.action_router")
        return HealthCheckResult("Modules", True, "All core modules imported successfully")
    except ImportError as e:
        return HealthCheckResult("Modules", False, f"Import error: {str(e)}")


def check_logs_directory() -> HealthCheckResult:
    """Ensure logs directory is writable."""
    import os
    try:
        os.makedirs("logs", exist_ok=True)
        test_file = "logs/.write_test"
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        return HealthCheckResult("Logs Directory", True, "Logs directory is writable")
    except Exception as e:
        return HealthCheckResult("Logs Directory", False, str(e))


def check_config() -> HealthCheckResult:
    """Validate config system is working."""
    try:
        assert settings.app_name == "GINI-AI"
        return HealthCheckResult("Config", True, f"Config loaded | ENV: {settings.app_env}")
    except Exception as e:
        return HealthCheckResult("Config", False, str(e))


def run_health_checks() -> SystemHealthReport:
    """
    Run all startup health checks.
    Returns a full report — critical failures should halt startup.
    """
    report = SystemHealthReport()
    checks = [
        check_config,
        check_environment,
        check_logs_directory,
        check_modules,
    ]

    for check_fn in checks:
        result = check_fn()
        if result.status:
            report.passed.append(result)
            log.info(f"  ✅ {result.name}: {result.message}")
        else:
            report.failed.append(result)
            log.warning(f"  ❌ {result.name}: {result.message}")

    log.info(report.summary())
    return report


__all__ = ["run_health_checks", "SystemHealthReport", "HealthCheckResult"]
