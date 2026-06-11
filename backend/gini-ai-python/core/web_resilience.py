# ============================================================
# GINI-ORACLE-1 — Web & Backend Resilience
# core/web_resilience.py
# ============================================================
"""
Resilience layer for web operations:
  - Browser failure recovery
  - URL validation and sanitization
  - Backend connection retry
  - API timeout handling

Strategies:
  1. Browser Failure → Try alternative browser, fallback to text
  2. Invalid URL → Suggest correction, search instead
  3. Timeout → Extend timeout, retry with backoff
  4. Connection Refused → Check backend status, retry
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, Dict, List
from enum import Enum

from utils.logger import get_logger
from core.resilience import (
    FailureMode, RecoveryStrategy, FailureContext,
    RetryPolicy, CircuitBreaker, get_recovery_manager
)

log = get_logger(__name__)


class WebFailureMode(str, Enum):
    """Web-specific failures."""
    BROWSER_NOT_FOUND = "browser_not_found"
    BROWSER_CRASH = "browser_crash"
    INVALID_URL = "invalid_url"
    CONNECTION_TIMEOUT = "connection_timeout"
    CONNECTION_REFUSED = "connection_refused"
    SSL_ERROR = "ssl_error"
    DNS_ERROR = "dns_error"
    UNKNOWN_HOST = "unknown_host"


@dataclass
class WebRecoveryAction:
    """Suggested recovery action for web failure."""
    fallback_mode: str  # "try_browser_X", "search_instead", "retry", "abort"
    user_message: str
    suggested_url: Optional[str] = None
    can_retry: bool = False
    suggestions: List[str] = None
    is_critical: bool = False

    def to_dict(self) -> dict:
        return {
            "fallback_mode": self.fallback_mode,
            "message": self.user_message,
            "suggested_url": self.suggested_url,
            "suggestions": self.suggestions or [],
            "can_retry": self.can_retry,
            "is_critical": self.is_critical,
        }


class WebResilienceManager:
    """Handles web operation resilience."""

    def __init__(self):
        self.recovery_manager = get_recovery_manager()
        
        # Browser priority order
        self.browser_order = ["chrome", "firefox", "edge", "safari", "brave"]
        self.failed_browsers = set()

        # Allowed URL schemes
        self.allowed_schemes = {"http", "https"}
        self.blocked_domains = {"localhost", "127.0.0.1", "internal"}

        # Register circuits
        self.recovery_manager.register_circuit(
            "browser_launcher",
            failure_threshold=3,
            recovery_timeout=10,
        )
        self.recovery_manager.register_circuit(
            "url_fetcher",
            failure_threshold=5,
            recovery_timeout=30,
        )

        # Retry policy for network requests
        self.retry_policy = RetryPolicy(
            max_attempts=3,
            initial_delay=1.0,
            max_delay=10.0,
        )

        log.info("🌐 WebResilienceManager initialized")

    # ── Browser Failure Recovery ──────────────────────────────

    async def handle_browser_not_found(self, browser_name: str) -> WebRecoveryAction:
        """Handle browser not installed."""
        log.error(f"🌐❌ Browser not found: {browser_name}")

        circuit = self.recovery_manager.get_circuit("browser_launcher")
        if circuit:
            circuit.failure_count += 1

        self.failed_browsers.add(browser_name)

        # Try alternative browser
        alt_browser = self._find_alternative_browser()
        if alt_browser:
            return WebRecoveryAction(
                fallback_mode="try_browser",
                user_message=f"{browser_name} not found. Trying {alt_browser} instead...",
                can_retry=True,
            )
        else:
            return WebRecoveryAction(
                fallback_mode="text_mode",
                user_message=f"No web browsers found. Please install a browser like Chrome or Firefox.",
                can_retry=False,
            )

    async def handle_browser_crash(self, browser_name: str) -> WebRecoveryAction:
        """Handle browser crash."""
        log.error(f"💥❌ Browser crash: {browser_name}")

        circuit = self.recovery_manager.get_circuit("browser_launcher")
        if circuit:
            circuit.failure_count += 1

        self.failed_browsers.add(browser_name)

        alt_browser = self._find_alternative_browser()
        if alt_browser:
            return WebRecoveryAction(
                fallback_mode="try_browser",
                user_message=f"{browser_name} crashed. Trying {alt_browser}...",
                can_retry=True,
            )
        else:
            return WebRecoveryAction(
                fallback_mode="retry",
                user_message="Browser crashed. Please try again.",
                can_retry=True,
            )

    # ── URL Validation & Correction ───────────────────────────

    async def handle_invalid_url(self, url: str) -> WebRecoveryAction:
        """Handle invalid URL with correction suggestions."""
        log.warning(f"🔗❌ Invalid URL: {url}")

        # Try to fix common URL issues
        fixed_url = self._fix_common_url_issues(url)
        if fixed_url and fixed_url != url:
            return WebRecoveryAction(
                fallback_mode="retry",
                user_message=f"Fixed URL format. Trying: {fixed_url}",
                suggested_url=fixed_url,
                can_retry=True,
            )

        # If it looks like a search query, search instead
        if not any(scheme in url for scheme in ["://", "."]):
            return WebRecoveryAction(
                fallback_mode="search",
                user_message=f"Opening search results for: {url}",
                suggested_url=f"https://www.google.com/search?q={url}",
                can_retry=True,
            )

        return WebRecoveryAction(
            fallback_mode="abort",
            user_message=f"Invalid URL: {url}. Please check and try again.",
            can_retry=False,
        )

    # ── Connection Timeout Recovery ───────────────────────────

    async def handle_connection_timeout(self, url: str, timeout_sec: int) -> WebRecoveryAction:
        """Handle connection timeout."""
        log.warning(f"⏱️❌ Connection timeout for {url} after {timeout_sec}s")

        circuit = self.recovery_manager.get_circuit("url_fetcher")
        if circuit:
            circuit.failure_count += 1

        # Suggest retrying with increased timeout
        return WebRecoveryAction(
            fallback_mode="retry",
            user_message="Connection timed out. Retrying with more time...",
            can_retry=True,
        )

    # ── Connection Refused Recovery ───────────────────────────

    async def handle_connection_refused(self, url: str, error: str) -> WebRecoveryAction:
        """Handle connection refused (backend down, etc)."""
        log.error(f"🚫❌ Connection refused for {url}: {error}")

        circuit = self.recovery_manager.get_circuit("url_fetcher")
        if circuit:
            circuit.failure_count += 1

        # Check if it's a local service
        if "localhost" in url or "127.0.0.1" in url:
            return WebRecoveryAction(
                fallback_mode="abort",
                user_message="Cannot connect to local service. Is it running?",
                can_retry=True,
                is_critical=True,
            )
        else:
            return WebRecoveryAction(
                fallback_mode="retry",
                user_message="Server not responding. Retrying...",
                can_retry=True,
            )

    # ── SSL/DNS Errors ────────────────────────────────────────

    async def handle_ssl_error(self, url: str) -> WebRecoveryAction:
        """Handle SSL certificate error."""
        log.error(f"🔒❌ SSL error for {url}")

        return WebRecoveryAction(
            fallback_mode="abort",
            user_message="Security certificate issue. Website may be unsafe.",
            can_retry=False,
            is_critical=True,
        )

    async def handle_dns_error(self, host: str) -> WebRecoveryAction:
        """Handle DNS resolution error."""
        log.error(f"🌐❌ DNS error for {host}")

        return WebRecoveryAction(
            fallback_mode="retry",
            user_message=f"Could not reach {host}. Retrying DNS resolution...",
            can_retry=True,
        )

    async def handle_unknown_host(self, host: str) -> WebRecoveryAction:
        """Handle unknown host."""
        log.error(f"❓❌ Unknown host: {host}")

        return WebRecoveryAction(
            fallback_mode="abort",
            user_message=f"Unknown host: {host}. Please check the address.",
            can_retry=False,
        )

    # ── Helper Methods ─────────────────────────────────────────

    def _find_alternative_browser(self) -> Optional[str]:
        """Find next working browser to try."""
        for browser in self.browser_order:
            if browser not in self.failed_browsers:
                return browser
        return None

    def _fix_common_url_issues(self, url: str) -> Optional[str]:
        """Attempt to fix common URL formatting issues."""
        url = url.strip()

        # Add http:// if missing
        if not any(url.startswith(scheme + "://") for scheme in self.allowed_schemes):
            if url.startswith("www."):
                return f"https://{url}"
            elif "." in url:
                return f"https://{url}"

        return url

    def validate_url(self, url: str) -> tuple[bool, Optional[str]]:
        """Validate URL before attempting connection."""
        url_lower = url.lower()

        # Check scheme
        scheme = url_lower.split("://")[0] if "://" in url_lower else None
        if scheme and scheme not in self.allowed_schemes:
            return False, f"Scheme not allowed: {scheme}"

        # Check for dangerous patterns
        if any(pattern in url_lower for pattern in ["javascript:", "data:", "file://"]):
            return False, "URL contains dangerous pattern"

        # Check blocked domains
        for blocked in self.blocked_domains:
            if blocked in url_lower:
                return False, f"Domain not allowed: {blocked}"

        return True, None

    # ── Backend Connection Health ──────────────────────────────

    async def check_backend_health(self, backend_url: str) -> tuple[bool, Optional[str]]:
        """Check if backend is reachable."""
        log.info(f"🏥 Checking backend health: {backend_url}")

        circuit = self.recovery_manager.get_circuit("url_fetcher")

        try:
            # This would normally use requests or aiohttp
            # For now, just simulate check
            await asyncio.sleep(0.5)
            return True, None
        except Exception as e:
            log.error(f"Backend health check failed: {e}")
            return False, str(e)

    # ── Status and Diagnostics ────────────────────────────────

    def get_status(self) -> dict:
        """Get web system status."""
        return {
            "failed_browsers": list(self.failed_browsers),
            "browser_launcher_circuit": self.recovery_manager.get_circuit("browser_launcher").status(),
            "url_fetcher_circuit": self.recovery_manager.get_circuit("url_fetcher").status(),
        }

    async def self_heal(self) -> dict:
        """Attempt web system self-healing."""
        log.info("🏥 Web system self-healing...")

        # Reset failed browsers list periodically
        self.failed_browsers.clear()

        return {
            "failed_browsers_reset": True,
            "status": "healthy",
        }


# ── Backend-Specific Resilience ───────────────────────────────

class BackendResilienceManager:
    """Handles backend API communication resilience."""

    def __init__(self):
        self.recovery_manager = get_recovery_manager()
        self.backend_url: Optional[str] = None
        self.last_successful_request: Optional[float] = None
        self.connection_attempts = 0

        # Register circuit for API calls
        self.recovery_manager.register_circuit(
            "api_gateway",
            failure_threshold=5,
            recovery_timeout=15,
        )

        # Retry policy for API calls
        self.retry_policy = RetryPolicy(
            max_attempts=3,
            initial_delay=0.5,
            max_delay=5.0,
        )

        log.info("🔗 BackendResilienceManager initialized")

    async def handle_backend_disconnect(self, error: str) -> dict:
        """Handle backend disconnect."""
        log.error(f"🔌❌ Backend disconnect: {error}")

        circuit = self.recovery_manager.get_circuit("api_gateway")
        if circuit:
            circuit.failure_count += 1

        return {
            "status": "error",
            "message": "Backend service is unavailable. Retrying...",
            "fallback_mode": "queue_request",
            "can_retry": True,
        }

    async def handle_api_timeout(self, endpoint: str, timeout_sec: int) -> dict:
        """Handle API timeout."""
        log.warning(f"⏱️❌ API timeout on {endpoint} after {timeout_sec}s")

        circuit = self.recovery_manager.get_circuit("api_gateway")
        if circuit:
            circuit.failure_count += 1

        return {
            "status": "timeout",
            "message": f"Request to {endpoint} timed out. Retrying...",
            "fallback_mode": "retry_with_backoff",
            "can_retry": True,
        }

    async def queue_request(self, request: dict) -> bool:
        """Queue a request for retry when backend recovers."""
        log.info(f"📋 Queueing request: {request.get('endpoint', 'unknown')}")
        # In production, this would persist to a queue
        return True

    def get_status(self) -> dict:
        """Get backend status."""
        return {
            "api_gateway_circuit": self.recovery_manager.get_circuit("api_gateway").status(),
            "last_successful_request": self.last_successful_request,
            "connection_attempts": self.connection_attempts,
        }


# ── Global instances ──────────────────────────────────

_web_resilience: Optional[WebResilienceManager] = None
_backend_resilience: Optional[BackendResilienceManager] = None


def get_web_resilience() -> WebResilienceManager:
    """Get or create global web resilience manager."""
    global _web_resilience
    if _web_resilience is None:
        _web_resilience = WebResilienceManager()
    return _web_resilience


def get_backend_resilience() -> BackendResilienceManager:
    """Get or create global backend resilience manager."""
    global _backend_resilience
    if _backend_resilience is None:
        _backend_resilience = BackendResilienceManager()
    return _backend_resilience


__all__ = [
    "WebResilienceManager",
    "BackendResilienceManager",
    "WebRecoveryAction",
    "WebFailureMode",
    "get_web_resilience",
    "get_backend_resilience",
]
