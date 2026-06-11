# ============================================================
# GINI-ORACLE-1 — Structured Production Event Logger
# utils/event_logger.py
# ============================================================
"""
Centralized structured event logger for production observability.

Tracks:
  ● commands        — raw input + parsed form + routing metadata
  ● intents         — detected intent, confidence, all scores
  ● execution_time  — per-request latency with stage breakdown
  ● failures        — typed errors with context + recovery info
  ● warnings        — low-confidence detections, degraded states
  ● voice_events    — mic/STT/TTS lifecycle events
  ● lifecycle       — bootstrap, startup, shutdown, signal events

All events are:
  1. Emitted to the main loguru logger at the appropriate level
  2. Written to a dedicated structured JSONL audit log
     (logs/events.jsonl) for machine consumption / dashboards
  3. Kept in an in-memory ring-buffer for the /diagnostics endpoint

Usage:
    from utils.event_logger import get_event_logger
    elog = get_event_logger()

    elog.command("open chrome", user_id="u1", session_id="s1")
    with elog.timed("routing"):
        result = await router.route(cmd)
    elog.intent(result.intent, result.confidence, result.all_scores)
"""

from __future__ import annotations

import json
import time
import uuid
import traceback
from collections import deque
from contextlib import contextmanager, asynccontextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence

from utils.logger import get_logger

log = get_logger(__name__)

# ── Constants ────────────────────────────────────────────────
_EVENTS_LOG_PATH = Path("logs/events.jsonl")
_RING_BUFFER_SIZE = 500          # events kept in memory
_SLOW_REQUEST_MS  = 2_000        # threshold for slow-request warning
_LOW_CONFIDENCE   = 0.55         # threshold for confidence warning


# ── Event types ───────────────────────────────────────────────

class EventType:
    COMMAND        = "command"
    INTENT         = "intent"
    EXECUTION_TIME = "execution_time"
    FAILURE        = "failure"
    WARNING        = "warning"
    VOICE          = "voice"
    LIFECYCLE      = "lifecycle"


# ── Event envelope ────────────────────────────────────────────

@dataclass
class Event:
    """Standardized envelope for every logged event."""
    event_id:   str
    event_type: str
    timestamp:  str
    payload:    Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id":   self.event_id,
            "event_type": self.event_type,
            "timestamp":  self.timestamp,
            **self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ── Timer context manager ─────────────────────────────────────

class _Timer:
    """Lightweight wall-clock timer."""
    def __init__(self):
        self._start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1_000


# ── Core event logger ─────────────────────────────────────────

class EventLogger:
    """
    Production-grade structured event logger.

    Thread-safe for logging calls; not designed for concurrent writes
    to the ring buffer from multiple OS threads — use asyncio patterns.
    """

    def __init__(self, log_path: Path = _EVENTS_LOG_PATH):
        self._log_path = log_path
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=_RING_BUFFER_SIZE)
        self._session_context: Dict[str, str] = {}   # correlation: {session_id: request_id}
        self._file_handle = None
        self._setup_file()

    # ── Internal helpers ──────────────────────────────────────

    def _setup_file(self) -> None:
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file_handle = open(self._log_path, "a", encoding="utf-8", buffering=1)
        except OSError as exc:
            log.warning(f"⚠️ Could not open event log at {self._log_path}: {exc}")
            self._file_handle = None

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _make_event(self, event_type: str, payload: Dict[str, Any]) -> Event:
        return Event(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp=self._now(),
            payload=payload,
        )

    def _emit(self, event: Event) -> None:
        """Write event to ring buffer and JSONL file."""
        self._buffer.append(event.to_dict())
        if self._file_handle:
            try:
                self._file_handle.write(event.to_json() + "\n")
            except OSError as exc:
                log.warning(f"Event log write failed: {exc}")

    # ── Public API ────────────────────────────────────────────

    # ── 1. Commands ───────────────────────────────────────────

    def command(
        self,
        raw_input: str,
        *,
        user_id: str = "unknown",
        session_id: Optional[str] = None,
        normalized: Optional[str] = None,
        tokens: Optional[List[str]] = None,
        entities: Optional[Dict] = None,
        request_id: Optional[str] = None,
    ) -> str:
        """
        Log an incoming command.

        Returns a request_id that callers can pass through the pipeline
        to correlate all events for a single request.
        """
        rid = request_id or str(uuid.uuid4())
        payload = {
            "request_id":  rid,
            "user_id":     user_id,
            "session_id":  session_id,
            "raw_input":   raw_input[:500],      # cap PII/length
            "normalized":  normalized,
            "token_count": len(tokens) if tokens else None,
            "entities":    entities or {},
        }
        event = self._make_event(EventType.COMMAND, payload)
        self._emit(event)
        log.debug(
            f"[CMD] rid={rid} user={user_id} "
            f"input='{raw_input[:60]}{'...' if len(raw_input) > 60 else ''}'"
        )
        return rid

    # ── 2. Intents ────────────────────────────────────────────

    def intent(
        self,
        detected_intent: str,
        confidence: float,
        all_scores: Optional[List[Dict]] = None,
        *,
        sub_intent: Optional[str] = None,
        request_id: Optional[str] = None,
        matched_keywords: Optional[List[str]] = None,
    ) -> None:
        """Log a detected intent with confidence scores."""
        is_low = confidence < _LOW_CONFIDENCE
        payload = {
            "request_id":       request_id,
            "intent":           detected_intent,
            "sub_intent":       sub_intent,
            "confidence":       round(confidence, 4),
            "is_low_confidence": is_low,
            "matched_keywords": matched_keywords or [],
            "all_scores":       all_scores or [],
        }
        event = self._make_event(EventType.INTENT, payload)
        self._emit(event)

        if is_low:
            log.warning(
                f"[INTENT] ⚠️ Low confidence={confidence:.2f} "
                f"intent={detected_intent} rid={request_id}"
            )
        else:
            log.info(
                f"[INTENT] {detected_intent}({confidence:.2f})"
                + (f" sub={sub_intent}" if sub_intent else "")
                + (f" rid={request_id}" if request_id else "")
            )

    # ── 3. Execution time ─────────────────────────────────────

    def execution_time(
        self,
        stage: str,
        elapsed_ms: float,
        *,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        intent: Optional[str] = None,
        success: bool = True,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Log execution time for a pipeline stage."""
        is_slow = elapsed_ms > _SLOW_REQUEST_MS
        payload = {
            "request_id": request_id,
            "user_id":    user_id,
            "stage":      stage,
            "elapsed_ms": round(elapsed_ms, 2),
            "intent":     intent,
            "success":    success,
            "is_slow":    is_slow,
            "metadata":   metadata or {},
        }
        event = self._make_event(EventType.EXECUTION_TIME, payload)
        self._emit(event)

        if is_slow:
            log.warning(
                f"[TIMING] ⚠️ SLOW stage={stage} "
                f"elapsed={elapsed_ms:.0f}ms rid={request_id}"
            )
        else:
            log.debug(
                f"[TIMING] stage={stage} elapsed={elapsed_ms:.1f}ms"
                + (f" rid={request_id}" if request_id else "")
            )

    @contextmanager
    def timed(
        self,
        stage: str,
        *,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        intent: Optional[str] = None,
    ):
        """
        Synchronous context manager that auto-logs execution time.

        Usage:
            with elog.timed("handler", request_id=rid):
                result = handler.handle(...)
        """
        timer = _Timer()
        success = True
        with timer:
            try:
                yield timer
            except Exception:
                success = False
                raise
            finally:
                self.execution_time(
                    stage,
                    timer.elapsed_ms,
                    request_id=request_id,
                    user_id=user_id,
                    intent=intent,
                    success=success,
                )

    @asynccontextmanager
    async def async_timed(
        self,
        stage: str,
        *,
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        intent: Optional[str] = None,
    ):
        """
        Async context manager that auto-logs execution time.

        Usage:
            async with elog.async_timed("pipeline", request_id=rid):
                result = await router.route(cmd)
        """
        timer = _Timer()
        success = True
        timer.__enter__()
        try:
            yield timer
        except Exception:
            success = False
            raise
        finally:
            timer.__exit__(None, None, None)
            self.execution_time(
                stage,
                timer.elapsed_ms,
                request_id=request_id,
                user_id=user_id,
                intent=intent,
                success=success,
            )

    # ── 4. Failures ───────────────────────────────────────────

    def failure(
        self,
        failure_mode: str,
        error_message: str,
        *,
        service: str = "unknown",
        request_id: Optional[str] = None,
        user_id: Optional[str] = None,
        exception: Optional[Exception] = None,
        recovery_action: Optional[str] = None,
        context: Optional[Dict] = None,
        critical: bool = False,
    ) -> None:
        """Log a failure with full context for post-mortem analysis."""
        payload = {
            "request_id":      request_id,
            "user_id":         user_id,
            "failure_mode":    failure_mode,
            "error_message":   error_message[:1000],
            "service":         service,
            "recovery_action": recovery_action,
            "critical":        critical,
            "context":         context or {},
            "traceback":       (
                traceback.format_exc()
                if exception is not None
                else None
            ),
        }
        event = self._make_event(EventType.FAILURE, payload)
        self._emit(event)

        log_fn = log.critical if critical else log.error
        log_fn(
            f"[FAILURE] {'🚨 CRITICAL ' if critical else ''}mode={failure_mode} "
            f"service={service} rid={request_id} | {error_message[:120]}"
            + (f"\n{traceback.format_exc()}" if exception else "")
        )

    # ── 5. Warnings ───────────────────────────────────────────

    def warning(
        self,
        warning_type: str,
        message: str,
        *,
        request_id: Optional[str] = None,
        service: Optional[str] = None,
        context: Optional[Dict] = None,
    ) -> None:
        """Log a structured warning (degraded state, low confidence, etc.)."""
        payload = {
            "request_id":   request_id,
            "warning_type": warning_type,
            "message":      message[:500],
            "service":      service,
            "context":      context or {},
        }
        event = self._make_event(EventType.WARNING, payload)
        self._emit(event)
        log.warning(
            f"[WARN] type={warning_type}"
            + (f" svc={service}" if service else "")
            + (f" rid={request_id}" if request_id else "")
            + f" | {message[:120]}"
        )

    # ── 6. Voice events ───────────────────────────────────────

    def voice_event(
        self,
        event_name: str,
        *,
        device: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error: Optional[str] = None,
        recovery: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """
        Log a voice pipeline event.

        event_name examples:
          mic_started, mic_stopped, mic_failure,
          stt_started, stt_complete, stt_timeout, stt_error,
          tts_started, tts_complete, tts_crash,
          device_switch, fallback_to_text
        """
        is_error = error is not None
        payload = {
            "voice_event":  event_name,
            "device":       device,
            "duration_ms":  duration_ms,
            "error":        error,
            "recovery":     recovery,
            "metadata":     metadata or {},
        }
        event = self._make_event(EventType.VOICE, payload)
        self._emit(event)

        if is_error:
            log.error(
                f"[VOICE] ❌ {event_name}"
                + (f" device={device}" if device else "")
                + f" | {error}"
                + (f" → recovery={recovery}" if recovery else "")
            )
        else:
            log.info(
                f"[VOICE] {event_name}"
                + (f" device={device}" if device else "")
                + (f" duration={duration_ms:.0f}ms" if duration_ms is not None else "")
            )

    # ── 7. Lifecycle events ───────────────────────────────────

    def lifecycle(
        self,
        phase: str,
        status: str,
        *,
        component: Optional[str] = None,
        elapsed_ms: Optional[float] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """
        Log a backend lifecycle event.

        phase examples:   bootstrap, startup, shutdown, signal
        status examples:  begin, complete, failed, degraded
        """
        is_error = status in ("failed", "error")
        payload = {
            "phase":      phase,
            "status":     status,
            "component":  component,
            "elapsed_ms": elapsed_ms,
            "error":      error,
            "metadata":   metadata or {},
        }
        event = self._make_event(EventType.LIFECYCLE, payload)
        self._emit(event)

        msg = (
            f"[LIFECYCLE] {phase}.{status}"
            + (f" component={component}" if component else "")
            + (f" elapsed={elapsed_ms:.0f}ms" if elapsed_ms is not None else "")
            + (f" | {error}" if error else "")
        )
        if is_error:
            log.error(msg)
        else:
            log.info(msg)

    # ── Ring buffer / diagnostics ─────────────────────────────

    def recent_events(
        self,
        limit: int = 50,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent events from the ring buffer."""
        events = list(self._buffer)
        if event_type:
            events = [e for e in events if e.get("event_type") == event_type]
        return events[-limit:]

    def stats(self) -> Dict[str, Any]:
        """Return event-type counts from the ring buffer."""
        counts: Dict[str, int] = {}
        for e in self._buffer:
            et = e.get("event_type", "unknown")
            counts[et] = counts.get(et, 0) + 1
        return {
            "total_buffered": len(self._buffer),
            "buffer_capacity": _RING_BUFFER_SIZE,
            "by_type": counts,
            "events_log_path": str(self._log_path),
        }

    def close(self) -> None:
        """Flush and close the JSONL file handle."""
        if self._file_handle:
            try:
                self._file_handle.flush()
                self._file_handle.close()
            except OSError:
                pass
            finally:
                self._file_handle = None


# ── Global singleton ─────────────────────────────────────────

_instance: Optional[EventLogger] = None


def get_event_logger() -> EventLogger:
    """Return the process-wide EventLogger singleton."""
    global _instance
    if _instance is None:
        _instance = EventLogger()
    return _instance


__all__ = [
    "EventLogger",
    "EventType",
    "Event",
    "get_event_logger",
]
