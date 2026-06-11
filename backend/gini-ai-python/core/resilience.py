# ============================================================
# GINI-ORACLE-1 — Resilience Layer
# core/resilience.py
# ============================================================
"""
Comprehensive resilience framework for handling failures:

Failure Modes Covered:
  1. Microphone failure (device unavailable, permission denied)
  2. Missing dependencies (TTS/STT packages not installed)
  3. App not found (registry lookup fails)
  4. Invalid command (parsing/validation errors)
  5. Browser failure (launch/connection issues)
  6. TTS crash (speech synthesis error)
  7. STT timeout (speech recognition timeout)
  8. Backend disconnect (API unreachable)

Strategies:
  - Automatic retry with exponential backoff
  - Circuit breaker pattern for external services
  - Fallback to alternatives (text when voice fails, etc.)
  - Graceful degradation (partial functionality)
  - Self-healing health checks
  - User-friendly error messages
  - Recovery state tracking
"""

import time
import asyncio
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Callable, Any, List, Dict
from datetime import datetime, timedelta

from utils.logger import get_logger

log = get_logger(__name__)


# ── Failure Categories ────────────────────────────────────────

class FailureMode(str, Enum):
    """Categories of failures the system can encounter."""
    MIC_FAILURE = "mic_failure"
    MISSING_DEPENDENCY = "missing_dependency"
    APP_NOT_FOUND = "app_not_found"
    INVALID_COMMAND = "invalid_command"
    BROWSER_FAILURE = "browser_failure"
    TTS_CRASH = "tts_crash"
    STT_TIMEOUT = "stt_timeout"
    BACKEND_DISCONNECT = "backend_disconnect"
    UNKNOWN = "unknown"


class RecoveryStrategy(str, Enum):
    """How to recover from a failure."""
    RETRY = "retry"              # Retry operation
    FALLBACK = "fallback"        # Use alternative
    DEGRADE = "degrade"          # Partial functionality
    WAIT = "wait"                # Wait and retry
    ABORT = "abort"              # Give up gracefully
    USER_INPUT = "user_input"    # Ask user for help


# ── Circuit Breaker ──────────────────────────────────────────

class CircuitState(str, Enum):
    """State of a circuit breaker."""
    CLOSED = "closed"       # Working normally
    OPEN = "open"           # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker pattern for external services.
    Prevents cascading failures by temporarily disabling a service.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        test_interval: int = 60,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.test_interval = test_interval

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.opened_at: Optional[datetime] = None

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute func if circuit is not open."""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_recovery():
                self.state = CircuitState.HALF_OPEN
                log.info(f"🔄 Circuit '{self.name}' entering HALF_OPEN state")
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit '{self.name}' is OPEN. Service unavailable."
                )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    async def call_async(self, func: Callable, *args, **kwargs) -> Any:
        """Execute async func if circuit is not open."""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_recovery():
                self.state = CircuitState.HALF_OPEN
                log.info(f"🔄 Circuit '{self.name}' entering HALF_OPEN state")
            else:
                raise CircuitBreakerOpenError(
                    f"Circuit '{self.name}' is OPEN. Service unavailable."
                )

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Reset circuit on successful call."""
        if self.state == CircuitState.HALF_OPEN:
            log.info(f"✅ Circuit '{self.name}' recovered → CLOSED")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None

    def _on_failure(self):
        """Record failure and open circuit if threshold exceeded."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()

        if self.state == CircuitState.HALF_OPEN:
            self.opened_at = datetime.now()
            log.error(
                f"Circuit '{self.name}' recovery probe failed after "
                f"{self.failure_count} failures"
            )
            return

        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = datetime.now()
            log.error(
                f"❌ Circuit '{self.name}' OPEN after {self.failure_count} failures"
            )

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if not self.opened_at:
            return False
        elapsed = (datetime.now() - self.opened_at).total_seconds()
        return elapsed >= self.recovery_timeout

    def status(self) -> dict:
        """Get circuit status."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self.failure_count,
            "threshold": self.failure_threshold,
            "last_failure": self.last_failure_time.isoformat() if self.last_failure_time else None,
        }


# ── Retry Policy ──────────────────────────────────────────────

@dataclass
class RetryPolicy:
    """Configuration for retry behavior."""
    max_attempts: int = 3
    initial_delay: float = 0.5  # seconds
    max_delay: float = 10.0     # seconds
    backoff_factor: float = 2.0
    jitter: bool = True

    async def execute_async(
        self,
        func: Callable,
        *args,
        on_retry: Optional[Callable] = None,
        **kwargs
    ) -> Any:
        """Execute async function with retries."""
        last_error = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                result = await func(*args, **kwargs)
                if attempt > 1:
                    log.info(f"✅ Succeeded on attempt {attempt}/{self.max_attempts}")
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_attempts:
                    delay = self._calculate_delay(attempt)
                    log.warning(
                        f"⏳ Attempt {attempt} failed: {str(e)[:50]}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    if on_retry:
                        await on_retry(attempt, e, delay)
                    await asyncio.sleep(delay)
                else:
                    log.error(
                        f"❌ Failed after {self.max_attempts} attempts: {str(e)[:100]}"
                    )

        raise last_error or Exception("Max retries exceeded")

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay."""
        delay = self.initial_delay * (self.backoff_factor ** (attempt - 1))
        delay = min(delay, self.max_delay)

        if self.jitter:
            import random
            delay *= (0.5 + random.random())

        return delay


# ── Failure Context ──────────────────────────────────────────

@dataclass
class FailureContext:
    """Information about a failure."""
    mode: FailureMode
    message: str
    exception: Optional[Exception] = None
    timestamp: datetime = field(default_factory=datetime.now)
    service: str = ""
    recoverable: bool = True
    recovery_strategy: RecoveryStrategy = RecoveryStrategy.RETRY
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "message": self.message,
            "service": self.service,
            "recoverable": self.recoverable,
            "strategy": self.recovery_strategy.value,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }


# ── Recovery Manager ──────────────────────────────────────────

class RecoveryManager:
    """
    Central manager for resilience strategies and recovery flows.
    Coordinates circuit breakers, retry policies, and fallbacks.
    """

    def __init__(self):
        self.circuits: Dict[str, CircuitBreaker] = {}
        self.retry_policies: Dict[str, RetryPolicy] = {}
        self.failure_history: List[FailureContext] = []
        self.max_history = 100

    def register_circuit(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
    ) -> CircuitBreaker:
        """Register a circuit breaker."""
        cb = CircuitBreaker(name, failure_threshold, recovery_timeout)
        self.circuits[name] = cb
        log.info(f"📍 Registered circuit breaker: {name}")
        return cb

    def register_retry_policy(
        self,
        name: str,
        max_attempts: int = 3,
        initial_delay: float = 0.5,
        max_delay: float = 10.0,
    ) -> RetryPolicy:
        """Register a retry policy."""
        policy = RetryPolicy(
            max_attempts=max_attempts,
            initial_delay=initial_delay,
            max_delay=max_delay,
        )
        self.retry_policies[name] = policy
        log.info(f"🔄 Registered retry policy: {name} (max={max_attempts})")
        return policy

    def record_failure(self, context: FailureContext):
        """Record a failure for monitoring."""
        self.failure_history.append(context)
        if len(self.failure_history) > self.max_history:
            self.failure_history.pop(0)
        log.warning(f"📌 Failure recorded: {context.mode.value} - {context.message}")

    def get_circuit(self, name: str) -> Optional[CircuitBreaker]:
        """Get a circuit breaker by name."""
        return self.circuits.get(name)

    def get_retry_policy(self, name: str) -> RetryPolicy:
        """Get a retry policy by name."""
        return self.retry_policies.get(name, RetryPolicy())

    def get_failure_report(self) -> dict:
        """Get summary of recent failures."""
        return {
            "total_failures": len(self.failure_history),
            "circuits": {name: cb.status() for name, cb in self.circuits.items()},
            "recent": [f.to_dict() for f in self.failure_history[-10:]],
        }


# ── Exceptions ────────────────────────────────────────────────

class ResilienceError(Exception):
    """Base resilience exception."""
    pass


class CircuitBreakerOpenError(ResilienceError):
    """Circuit breaker is open."""
    pass


class RecoveryFailedError(ResilienceError):
    """Recovery attempt failed."""
    pass


# ── Global instance ──────────────────────────────────────────

_recovery_manager: Optional[RecoveryManager] = None


def get_recovery_manager() -> RecoveryManager:
    """Get or create global recovery manager."""
    global _recovery_manager
    if _recovery_manager is None:
        _recovery_manager = RecoveryManager()
        log.info("🛡️ Recovery Manager initialized")
    return _recovery_manager


__all__ = [
    "FailureMode",
    "RecoveryStrategy",
    "CircuitBreaker",
    "CircuitState",
    "RetryPolicy",
    "FailureContext",
    "RecoveryManager",
    "CircuitBreakerOpenError",
    "RecoveryFailedError",
    "get_recovery_manager",
]
