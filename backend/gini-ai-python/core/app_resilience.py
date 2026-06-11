# ============================================================
# GINI-ORACLE-1 — App Resilience
# core/app_resilience.py
# ============================================================
"""
Resilience layer for app control and command execution:
  - App not found recovery
  - Invalid command handling
  - Permission errors
  - Process timeout recovery
  - Alternative app suggestions

Strategies:
  1. App Not Found → Suggest similar apps, offer installation, fallback to web
  2. Invalid Command → Validate syntax, suggest corrections
  3. Permission Denied → Suggest privilege escalation or alternative
  4. Process Timeout → Kill process gracefully, report to user
  5. Already Running → Offer to focus or close first
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, List, Dict
from enum import Enum

from utils.logger import get_logger
from core.resilience import (
    FailureMode, RecoveryStrategy, FailureContext,
    RetryPolicy, get_recovery_manager
)

log = get_logger(__name__)


class AppFailureMode(str, Enum):
    """App-specific failures."""
    APP_NOT_FOUND = "app_not_found"
    APP_NOT_INSTALLED = "app_not_installed"
    PERMISSION_DENIED = "permission_denied"
    PROCESS_TIMEOUT = "process_timeout"
    PROCESS_CRASH = "process_crash"
    INVALID_COMMAND = "invalid_command"
    COMMAND_SYNTAX_ERROR = "command_syntax_error"
    APP_ALREADY_RUNNING = "app_already_running"


@dataclass
class AppRecoveryAction:
    """Suggested recovery action for app failure."""
    fallback_mode: str  # "install", "use_web", "try_similar", "retry", "abort"
    user_message: str
    suggestions: List[str]  # Alternative apps
    can_retry: bool
    is_critical: bool = False

    def to_dict(self) -> dict:
        return {
            "fallback_mode": self.fallback_mode,
            "message": self.user_message,
            "suggestions": self.suggestions,
            "can_retry": self.can_retry,
            "is_critical": self.is_critical,
        }


class AppResilienceManager:
    """Handles app execution resilience."""

    def __init__(self):
        self.recovery_manager = get_recovery_manager()
        
        # Common app aliases for fuzzy matching
        self.app_aliases = {
            "chrome": ["chromium", "google chrome", "chrome browser"],
            "firefox": ["mozilla", "mozilla firefox"],
            "edge": ["microsoft edge", "edge browser"],
            "vscode": ["visual studio code", "code editor"],
            "notepad": ["text editor", "txt editor"],
            "vlc": ["media player", "video player"],
            "spotify": ["music player", "song player"],
            "discord": ["chat app", "voice chat"],
            "telegram": ["messaging app", "messenger"],
            "zoom": ["video call", "meeting app"],
        }

        # Register circuit for app launching
        self.recovery_manager.register_circuit(
            "app_launcher",
            failure_threshold=5,
            recovery_timeout=30,
        )

        log.info("📱 AppResilienceManager initialized")

    # ── App Not Found Recovery ─────────────────────────────────

    async def handle_app_not_found(self, app_name: str) -> AppRecoveryAction:
        """
        Handle app not found error.
        
        Returns suggestions for similar apps or web alternatives.
        """
        log.error(f"📱❌ App not found: {app_name}")

        circuit = self.recovery_manager.get_circuit("app_launcher")
        if circuit:
            circuit.failure_count += 1

        # Find similar apps
        similar_apps = self._find_similar_apps(app_name)

        if similar_apps:
            return AppRecoveryAction(
                fallback_mode="try_similar",
                user_message=f"{app_name} not found. Did you mean: {', '.join(similar_apps[:2])}?",
                suggestions=similar_apps,
                can_retry=True,
            )
        else:
            return AppRecoveryAction(
                fallback_mode="use_web",
                user_message=f"I couldn't find {app_name}. Try opening it in a web browser instead?",
                suggestions=["web_version"],
                can_retry=False,
            )

    # ── Invalid Command Recovery ──────────────────────────────

    async def handle_invalid_command(self, command: str, error: str) -> AppRecoveryAction:
        """Handle invalid command with syntax suggestions."""
        log.error(f"❌ Invalid command: {command} - {error}")

        # Try to extract app name and suggest valid syntax
        suggested_fix = self._suggest_command_fix(command)

        if suggested_fix:
            return AppRecoveryAction(
                fallback_mode="retry",
                user_message=f"Invalid command syntax. Did you mean: {suggested_fix}?",
                suggestions=[suggested_fix],
                can_retry=True,
            )
        else:
            return AppRecoveryAction(
                fallback_mode="abort",
                user_message=f"I couldn't understand the command. Try: 'open [app name]' or 'close [app name]'",
                suggestions=["open chrome", "close spotify"],
                can_retry=False,
            )

    # ── Permission Denied Recovery ─────────────────────────────

    async def handle_permission_denied(self, command: str) -> AppRecoveryAction:
        """Handle permission denied error."""
        log.error(f"🔒❌ Permission denied: {command}")

        return AppRecoveryAction(
            fallback_mode="prompt_user",
            user_message="This command requires administrator/sudo privileges. Please run as admin.",
            suggestions=["Run as administrator"],
            can_retry=True,
            is_critical=True,
        )

    # ── Process Timeout Recovery ───────────────────────────────

    async def handle_process_timeout(self, app_name: str, timeout_sec: int) -> AppRecoveryAction:
        """Handle process timeout."""
        log.warning(f"⏱️❌ Process timeout for {app_name} after {timeout_sec}s")

        return AppRecoveryAction(
            fallback_mode="kill_and_retry",
            user_message=f"{app_name} is taking too long to respond. Attempting to close it...",
            suggestions=["Trying again"],
            can_retry=True,
        )

    # ── Process Crash Recovery ────────────────────────────────

    async def handle_process_crash(self, app_name: str, error_code: int) -> AppRecoveryAction:
        """Handle process crash."""
        log.error(f"💥❌ {app_name} crashed with code {error_code}")

        if error_code == -1:
            message = f"{app_name} crashed unexpectedly. Try restarting your computer."
            retry = False
        else:
            message = f"{app_name} crashed. Retrying..."
            retry = True

        return AppRecoveryAction(
            fallback_mode="retry" if retry else "abort",
            user_message=message,
            suggestions=["Retry", "Use alternative"],
            can_retry=retry,
            is_critical=True,
        )

    # ── App Already Running ────────────────────────────────────

    async def handle_app_already_running(self, app_name: str) -> AppRecoveryAction:
        """Handle app already running error."""
        log.info(f"📱ℹ️ {app_name} already running")

        return AppRecoveryAction(
            fallback_mode="focus",
            user_message=f"{app_name} is already running. Bringing it to focus.",
            suggestions=["OK"],
            can_retry=False,
        )

    # ── Helper Methods ─────────────────────────────────────────

    def _find_similar_apps(self, app_name: str, max_suggestions: int = 3) -> List[str]:
        """Find similar app names using aliases and fuzzy matching."""
        app_lower = app_name.lower()
        similar = []

        # Check aliases
        for canonical, aliases in self.app_aliases.items():
            for alias in aliases:
                if self._string_similarity(app_lower, alias.lower()) > 0.7:
                    similar.append(canonical)
                    break

        return similar[:max_suggestions]

    def _suggest_command_fix(self, command: str) -> Optional[str]:
        """Suggest correction for invalid command."""
        command_lower = command.lower()

        # Common patterns
        if "open" in command_lower and len(command_lower.split()) < 2:
            return "Try: 'open [app name]'"
        elif "close" in command_lower and len(command_lower.split()) < 2:
            return "Try: 'close [app name]'"
        elif "launch" in command_lower:
            # Convert "launch" to "open"
            fixed = command_lower.replace("launch", "open", 1)
            return f"Try: '{fixed}'"
        elif "kill" in command_lower and len(command_lower.split()) < 2:
            return "Try: 'kill [app name]'"

        return None

    def _string_similarity(self, s1: str, s2: str) -> float:
        """Simple string similarity (0-1)."""
        if s1 == s2:
            return 1.0
        if s1 in s2 or s2 in s1:
            return 0.9
        
        # Levenshtein-like distance
        from difflib import SequenceMatcher
        return SequenceMatcher(None, s1, s2).ratio()

    # ── Validation ─────────────────────────────────────────────

    async def validate_app_name(self, app_name: str) -> tuple[bool, Optional[str]]:
        """Validate app name before launching."""
        if not app_name or len(app_name.strip()) == 0:
            return False, "App name cannot be empty"

        if len(app_name) > 50:
            return False, "App name too long"

        dangerous_patterns = ["rm -rf", "format", "shutdown", "del /s"]
        if any(pattern in app_name.lower() for pattern in dangerous_patterns):
            return False, "App name looks like a command, not an app"

        if any(c in app_name for c in ["<", ">", "|", "&", ";", "$", "`", "/"]):
            return False, "App name contains invalid characters"

        return True, None

    async def validate_command(self, command: str) -> tuple[bool, Optional[str]]:
        """Validate command syntax."""
        if not command or len(command.strip()) == 0:
            return False, "Command cannot be empty"

        if len(command) > 1000:
            return False, "Command too long"

        # Dangerous patterns
        dangerous = ["rm -rf", "format", "shutdown /s", "del /s"]
        for pattern in dangerous:
            if pattern in command.lower():
                return False, f"Dangerous command pattern detected: {pattern}"

        return True, None

    # ── Status and Diagnostics ────────────────────────────────

    def get_status(self) -> dict:
        """Get app system status."""
        return {
            "app_launcher_circuit": self.recovery_manager.get_circuit("app_launcher").status(),
        }

    async def self_heal(self) -> dict:
        """Attempt app system self-healing."""
        log.info("🏥 App system self-healing...")
        
        results = {
            "apps_detected": [],
            "status": "healthy",
        }

        # Could check for installed apps, processes, etc.
        return results


# ── Global instance ──────────────────────────────────────

_app_resilience: Optional[AppResilienceManager] = None


def get_app_resilience() -> AppResilienceManager:
    """Get or create global app resilience manager."""
    global _app_resilience
    if _app_resilience is None:
        _app_resilience = AppResilienceManager()
    return _app_resilience


__all__ = [
    "AppResilienceManager",
    "AppRecoveryAction",
    "AppFailureMode",
    "get_app_resilience",
]
