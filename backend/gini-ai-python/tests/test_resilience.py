# ============================================================
# GINI-ORACLE-1 — Resilience Layer Tests
# tests/test_resilience.py
# ============================================================

import pytest
import asyncio
from datetime import datetime, timedelta

from core.resilience import (
    CircuitBreaker, CircuitState, RetryPolicy, FailureContext,
    FailureMode, RecoveryStrategy, RecoveryManager, RecoveryFailedError,
    CircuitBreakerOpenError
)
from core.voice_resilience import VoiceResilienceManager, VoiceFailureMode
from core.app_resilience import AppResilienceManager, AppFailureMode
from core.web_resilience import WebResilienceManager, BackendResilienceManager
from core.dependency_validator import DependencyValidator, DependencyStatus
from core.resilience_coordinator import ResilienceCoordinator, SystemHealth


# ── Circuit Breaker Tests ─────────────────────────────────────

class TestCircuitBreaker:
    """Test circuit breaker pattern."""

    def test_circuit_starts_closed(self):
        """Circuit breaker should start in CLOSED state."""
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_circuit_opens_after_threshold(self):
        """Circuit should open after failure threshold."""
        cb = CircuitBreaker("test", failure_threshold=3)

        def failing_func():
            raise ValueError("test error")

        # Fail 3 times
        for _ in range(3):
            try:
                cb.call(failing_func)
            except ValueError:
                pass

        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 3

    def test_circuit_rejects_calls_when_open(self):
        """Circuit should reject calls when OPEN."""
        cb = CircuitBreaker("test", failure_threshold=1)

        def failing_func():
            raise ValueError("test error")

        # Make it fail once
        try:
            cb.call(failing_func)
        except ValueError:
            pass

        # Now circuit is OPEN, next call should raise CircuitBreakerOpenError
        with pytest.raises(CircuitBreakerOpenError):
            cb.call(lambda: "success")

    def test_circuit_resets_on_success(self):
        """Circuit should reset after successful call."""
        cb = CircuitBreaker("test", failure_threshold=3)

        # Cause some failures
        for _ in range(2):
            try:
                cb.call(lambda: 1 / 0)
            except ZeroDivisionError:
                pass

        assert cb.failure_count == 2

        # Successful call should reset
        result = cb.call(lambda: "success")
        assert result == "success"
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_circuit_half_open_state(self):
        """Circuit should transition through HALF_OPEN state."""
        cb = CircuitBreaker(
            "test",
            failure_threshold=1,
            recovery_timeout=0,  # Immediate recovery
        )

        # Make it fail
        try:
            cb.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

        assert cb.state == CircuitState.OPEN

        # Should transition to HALF_OPEN on next attempt
        # (because recovery timeout is 0)
        try:
            cb.call(lambda: 1 / 0)
        except ZeroDivisionError:
            pass

        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_async_circuit_breaker(self):
        """Test circuit breaker with async functions."""
        cb = CircuitBreaker("test_async", failure_threshold=2)

        async def async_success():
            return "success"

        async def async_failure():
            raise ValueError("async error")

        # Success should work
        result = await cb.call_async(async_success)
        assert result == "success"

        # Failures
        for _ in range(2):
            try:
                await cb.call_async(async_failure)
            except ValueError:
                pass

        # Circuit should be open now
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call_async(async_success)


# ── Retry Policy Tests ────────────────────────────────────────

class TestRetryPolicy:
    """Test retry policy with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_success_on_first_attempt(self):
        """Should succeed on first attempt without retrying."""
        policy = RetryPolicy(max_attempts=3)

        attempt_count = {"count": 0}

        async def success_func():
            attempt_count["count"] += 1
            return "success"

        result = await policy.execute_async(success_func)
        assert result == "success"
        assert attempt_count["count"] == 1

    @pytest.mark.asyncio
    async def test_retry_succeeds_after_failures(self):
        """Should succeed after retrying failed attempts."""
        policy = RetryPolicy(max_attempts=3, initial_delay=0.01)

        attempt_count = {"count": 0}

        async def fail_twice_then_succeed():
            attempt_count["count"] += 1
            if attempt_count["count"] < 3:
                raise ValueError("not yet")
            return "success"

        result = await policy.execute_async(fail_twice_then_succeed)
        assert result == "success"
        assert attempt_count["count"] == 3

    @pytest.mark.asyncio
    async def test_retry_exhaustion(self):
        """Should raise after max attempts exceeded."""
        policy = RetryPolicy(max_attempts=2, initial_delay=0.01)

        async def always_fail():
            raise ValueError("always fails")

        with pytest.raises(ValueError):
            await policy.execute_async(always_fail)

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Retry delay should increase exponentially."""
        policy = RetryPolicy(
            max_attempts=4,
            initial_delay=0.1,
            backoff_factor=2.0,
            jitter=False,
        )

        delays = []

        async def on_retry(attempt, error, delay):
            delays.append(delay)

        attempt_count = {"count": 0}

        async def fail_three_times():
            attempt_count["count"] += 1
            if attempt_count["count"] < 4:
                raise ValueError()
            return "success"

        result = await policy.execute_async(fail_three_times, on_retry=on_retry)
        assert result == "success"

        # Verify exponential increase
        assert delays[0] < delays[1]
        assert delays[1] < delays[2]


# ── Failure Context Tests ────────────────────────────────────

class TestFailureContext:
    """Test failure context tracking."""

    def test_failure_context_creation(self):
        """Should create failure context with metadata."""
        context = FailureContext(
            mode=FailureMode.MIC_FAILURE,
            message="No microphone devices",
            service="voice_engine",
            metadata={"devices": 0},
        )

        assert context.mode == FailureMode.MIC_FAILURE
        assert context.message == "No microphone devices"
        assert context.service == "voice_engine"
        assert context.metadata["devices"] == 0

    def test_failure_context_to_dict(self):
        """Should convert to dict with ISO timestamp."""
        context = FailureContext(
            mode=FailureMode.APP_NOT_FOUND,
            message="Chrome not installed",
            service="app_control",
        )

        d = context.to_dict()
        assert d["mode"] == "app_not_found"
        assert d["service"] == "app_control"
        assert "timestamp" in d


# ── Recovery Manager Tests ────────────────────────────────────

class TestRecoveryManager:
    """Test central recovery manager."""

    def test_recovery_manager_creation(self):
        """Should create and initialize recovery manager."""
        mgr = RecoveryManager()
        assert len(mgr.circuits) == 0
        assert len(mgr.failure_history) == 0

    def test_register_circuit(self):
        """Should register circuit breakers."""
        mgr = RecoveryManager()
        cb = mgr.register_circuit("test", failure_threshold=5)
        assert mgr.get_circuit("test") is cb

    def test_register_retry_policy(self):
        """Should register retry policies."""
        mgr = RecoveryManager()
        policy = mgr.register_retry_policy("test", max_attempts=3)
        assert mgr.get_retry_policy("test") is policy

    def test_record_failure(self):
        """Should record failures in history."""
        mgr = RecoveryManager()
        context = FailureContext(
            mode=FailureMode.MIC_FAILURE,
            message="Test failure",
        )
        mgr.record_failure(context)
        assert len(mgr.failure_history) == 1

    def test_failure_history_limit(self):
        """Should limit failure history size."""
        mgr = RecoveryManager()
        mgr.max_history = 10

        for i in range(20):
            context = FailureContext(
                mode=FailureMode.MIC_FAILURE,
                message=f"Failure {i}",
            )
            mgr.record_failure(context)

        assert len(mgr.failure_history) == 10

    def test_get_failure_report(self):
        """Should generate failure report."""
        mgr = RecoveryManager()
        cb = mgr.register_circuit("test")
        context = FailureContext(
            mode=FailureMode.MIC_FAILURE,
            message="Test",
        )
        mgr.record_failure(context)

        report = mgr.get_failure_report()
        assert "total_failures" in report
        assert "circuits" in report
        assert "recent" in report


# ── Voice Resilience Tests ────────────────────────────────────

class TestVoiceResilienceManager:
    """Test voice system resilience."""

    @pytest.mark.asyncio
    async def test_mic_failure_recovery(self):
        """Should handle microphone failure."""
        mgr = VoiceResilienceManager()
        action = await mgr.handle_mic_failure("No microphone found")
        assert action.fallback_mode == "text_input"
        assert action.can_retry is True

    @pytest.mark.asyncio
    async def test_mic_permission_error(self):
        """Should handle permission denied."""
        mgr = VoiceResilienceManager()
        action = await mgr.handle_mic_failure("Permission denied")
        assert "permission" in action.user_message.lower()

    @pytest.mark.asyncio
    async def test_stt_timeout_recovery(self):
        """Should handle STT timeout."""
        mgr = VoiceResilienceManager()
        action = await mgr.handle_stt_timeout(10.0, max_timeout=30.0)
        assert action.fallback_mode == "retry_with_timeout"
        assert action.suggested_timeout is not None

    @pytest.mark.asyncio
    async def test_tts_crash_recovery(self):
        """Should handle TTS crash."""
        mgr = VoiceResilienceManager()
        action = await mgr.handle_tts_crash("TTS engine crashed")
        assert action.fallback_mode == "text_only"
        assert not mgr.tts_enabled

    def test_voice_status(self):
        """Should report voice system status."""
        mgr = VoiceResilienceManager()
        status = mgr.get_status()
        assert "mic_available" in status
        assert "tts_enabled" in status
        assert "circuits" in status


# ── App Resilience Tests ──────────────────────────────────────

class TestAppResilienceManager:
    """Test app control resilience."""

    @pytest.mark.asyncio
    async def test_app_not_found_recovery(self):
        """Should handle app not found."""
        mgr = AppResilienceManager()
        action = await mgr.handle_app_not_found("NotARealApp")
        assert action.fallback_mode in ["try_similar", "use_web"]

    @pytest.mark.asyncio
    async def test_invalid_command_recovery(self):
        """Should suggest command fixes."""
        mgr = AppResilienceManager()
        action = await mgr.handle_invalid_command("open", "Missing app name")
        assert "Try:" in action.user_message or action.fallback_mode == "abort"

    @pytest.mark.asyncio
    async def test_app_validation(self):
        """Should validate app names."""
        mgr = AppResilienceManager()

        # Valid
        valid, error = await mgr.validate_app_name("Chrome")
        assert valid is True

        # Invalid
        valid, error = await mgr.validate_app_name("")
        assert valid is False

        valid, error = await mgr.validate_app_name("a" * 100)
        assert valid is False

        valid, error = await mgr.validate_app_name("rm -rf /")
        assert valid is False

    @pytest.mark.asyncio
    async def test_command_validation(self):
        """Should validate commands."""
        mgr = AppResilienceManager()

        # Valid
        valid, error = await mgr.validate_command("open chrome")
        assert valid is True

        # Invalid
        valid, error = await mgr.validate_command("rm -rf /")
        assert valid is False


# ── Web Resilience Tests ──────────────────────────────────────

class TestWebResilienceManager:
    """Test web operation resilience."""

    @pytest.mark.asyncio
    async def test_browser_not_found_recovery(self):
        """Should handle browser not found."""
        mgr = WebResilienceManager()
        action = await mgr.handle_browser_not_found("NotaBrowser")
        assert action.fallback_mode in ["try_browser", "text_mode"]

    @pytest.mark.asyncio
    async def test_invalid_url_recovery(self):
        """Should fix invalid URLs."""
        mgr = WebResilienceManager()
        action = await mgr.handle_invalid_url("invalid")
        assert action.fallback_mode in ["retry", "search", "abort"]

    @pytest.mark.asyncio
    async def test_url_validation(self):
        """Should validate URLs."""
        mgr = WebResilienceManager()

        # Valid
        valid, error = mgr.validate_url("https://google.com")
        assert valid is True

        # Invalid scheme
        valid, error = mgr.validate_url("javascript:alert('xss')")
        assert valid is False

        # Blocked domain
        valid, error = mgr.validate_url("http://localhost:8000")
        assert valid is False

    def test_fix_common_url_issues(self):
        """Should fix common URL issues."""
        mgr = WebResilienceManager()

        # Should add https://
        fixed = mgr._fix_common_url_issues("google.com")
        assert fixed.startswith("https://")


# ── Dependency Validator Tests ────────────────────────────────

class TestDependencyValidator:
    """Test dependency validation."""

    @pytest.mark.asyncio
    async def test_check_critical_packages(self):
        """Should check critical packages."""
        validator = DependencyValidator()
        checks = await validator._check_critical_packages()
        assert len(checks) > 0
        # FastAPI should be installed
        assert any(c.name == "fastapi" for c in checks)

    def test_get_report(self):
        """Should generate dependency report."""
        validator = DependencyValidator()
        report = validator.get_report()
        assert "healthy" in report
        assert "total_checks" in report
        assert "installed" in report
        assert "missing" in report


# ── Resilience Coordinator Tests ──────────────────────────────

class TestResilienceCoordinator:
    """Test master resilience coordinator."""

    def test_coordinator_creation(self):
        """Should create coordinator."""
        coord = ResilienceCoordinator()
        assert coord.initialized is False
        assert not coord.health.is_healthy

    @pytest.mark.asyncio
    async def test_coordinator_initialization(self):
        """Should initialize all subsystems."""
        coord = ResilienceCoordinator()
        success = await coord.initialize()
        assert success is True
        assert coord.initialized is True

    @pytest.mark.asyncio
    async def test_handle_mic_failure(self):
        """Should route mic failures to voice resilience."""
        coord = ResilienceCoordinator()
        await coord.initialize()

        recovery = await coord.handle_error(
            FailureMode.MIC_FAILURE,
            "No microphone devices",
            context={"available_devices": []},
        )

        assert recovery["fallback_mode"] == "text_input"
        assert recovery["can_retry"] is True

    @pytest.mark.asyncio
    async def test_handle_app_not_found(self):
        """Should route app failures to app resilience."""
        coord = ResilienceCoordinator()
        await coord.initialize()

        recovery = await coord.handle_error(
            FailureMode.APP_NOT_FOUND,
            "Chrome not found",
            context={"app_name": "chrome"},
        )

        assert recovery["fallback_mode"] in ["try_similar", "use_web"]

    @pytest.mark.asyncio
    async def test_handle_missing_dependency(self):
        """Should degrade affected feature when a dependency is missing."""
        coord = ResilienceCoordinator()
        await coord.initialize()

        recovery = await coord.handle_error(
            FailureMode.MISSING_DEPENDENCY,
            "pyaudio is missing",
            context={"dependency": "pyaudio", "feature": "voice"},
        )

        assert recovery["fallback_mode"] == "feature_disabled"
        assert recovery["can_retry"] is True
        assert recovery["failure_mode"] == "missing_dependency"

    @pytest.mark.asyncio
    async def test_handle_invalid_command_recovery_payload(self):
        """Should return normalized recovery payload for invalid commands."""
        coord = ResilienceCoordinator()

        recovery = await coord.handle_error(
            FailureMode.INVALID_COMMAND,
            "Missing app name",
            context={"command": "open"},
        )

        assert recovery["failure_mode"] == "invalid_command"
        assert recovery["fallback_mode"] in ["retry", "abort"]
        assert "message" in recovery

    @pytest.mark.asyncio
    async def test_handle_browser_failure(self):
        """Should recover from browser launch failures."""
        coord = ResilienceCoordinator()

        recovery = await coord.handle_error(
            FailureMode.BROWSER_FAILURE,
            "browser failed",
            context={"browser_name": "chrome"},
        )

        assert recovery["failure_mode"] == "browser_failure"
        assert recovery["fallback_mode"] in ["try_browser", "retry"]
        assert "message" in recovery

    @pytest.mark.asyncio
    async def test_handle_backend_disconnect(self):
        """Should queue requests when backend disconnects."""
        coord = ResilienceCoordinator()

        recovery = await coord.handle_error(
            FailureMode.BACKEND_DISCONNECT,
            "connection refused",
            context={"service": "api_gateway"},
        )

        assert recovery["fallback_mode"] == "queue_request"
        assert recovery["can_retry"] is True
        assert recovery["failure_mode"] == "backend_disconnect"

    @pytest.mark.asyncio
    async def test_validate_before_operation(self):
        """Should validate before operations."""
        coord = ResilienceCoordinator()
        await coord.initialize()

        can_proceed, error = await coord.validate_before_operation(
            "voice_capture"
        )

        # Should be some kind of result
        assert isinstance(can_proceed, bool)

    @pytest.mark.asyncio
    async def test_trigger_self_healing(self):
        """Should trigger self-healing."""
        coord = ResilienceCoordinator()
        await coord.initialize()

        results = await coord.trigger_self_healing()
        assert "voice" in results
        assert "app" in results
        assert "overall_status" in results

    def test_get_status(self):
        """Should report status."""
        coord = ResilienceCoordinator()
        status = coord.get_status()
        assert "initialized" in status
        assert "healthy" in status
        assert "subsystems" in status

    def test_get_health(self):
        """Should report health."""
        coord = ResilienceCoordinator()
        health = coord.get_health()
        assert health["healthy"] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
