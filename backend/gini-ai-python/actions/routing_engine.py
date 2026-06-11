# ============================================================
# GINI-ORACLE-1 — Routing Engine (Master Router)
# actions/routing_engine.py
# ============================================================
"""
The RoutingEngine is the single entry point for all natural
language commands. It orchestrates the full pipeline:

  raw text
    → CommandParser      (normalize + tokenize + extract entities)
    → IntentDetector     (score all 8 intents, pick best)
    → Handler dispatch   (route to correct modular handler)
    → FallbackHandler    (if confidence too low or error)
    → RouteResult        (structured response back to assistant)

Design principles:
  - Stateless pipeline (safe for concurrent requests)
  - Never raises — always returns a RouteResult
  - Extensible: add new handlers by registering them
  - Full audit trail in RouteResult
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, List
from actions.command_parser import CommandParser, ParsedCommand
from actions.intent_detector import (
    IntentDetector, IntentResult,
    INTENT_UNKNOWN, CONFIDENCE_MEDIUM,
    INTENT_APP_CONTROL, INTENT_SYSTEM_CONTROL, INTENT_MEDIA_CONTROL,
    INTENT_WEB_SEARCH, INTENT_UTILITY, INTENT_QUESTION_ANSWER,
    INTENT_MEMORY,
)
from actions.fallback_handler import FallbackHandler
from actions.handlers import (
    AppControlHandler, SystemControlHandler, MediaControlHandler,
    WebSearchHandler, UtilityHandler, QuestionAnswerHandler,
    MemoryHandler, UnknownHandler, BaseIntentHandler,
)
from utils.logger import get_logger
from utils.event_logger import get_event_logger

log = get_logger(__name__)
elog = get_event_logger()


@dataclass
class RouteResult:
    """Full result of the routing pipeline for one command."""
    status: str                          # "ok" | "fallback" | "error"
    intent: str                          # Detected intent
    sub_intent: Optional[str]            # Sub-action within intent
    confidence: float                    # 0.0 – 1.0
    response: str                        # Human-readable response
    input_raw: str                       # Original user input
    input_normalized: str                # Parsed/normalized input
    handler_data: dict = field(default_factory=dict)   # Extra data from handler
    all_scores: List[dict] = field(default_factory=list)  # All intent scores
    entities: dict = field(default_factory=dict)       # Extracted entities
    request_id: Optional[str] = None    # Correlation ID for this request

    @property
    def is_confident(self) -> bool:
        return self.confidence >= CONFIDENCE_MEDIUM

    def to_dict(self) -> dict:
        return {
            "status":           self.status,
            "intent":           self.intent,
            "sub_intent":       self.sub_intent,
            "confidence":       round(self.confidence, 3),
            "response":         self.response,
            "input_raw":        self.input_raw,
            "input_normalized": self.input_normalized,
            "entities":         self.entities,
            "handler_data":     self.handler_data,
            "request_id":       self.request_id,
        }


class RoutingEngine:
    """
    Master router for all Gini natural language commands.
    Stateless — create once, reuse forever.
    """

    def __init__(self, confidence_threshold: float = CONFIDENCE_MEDIUM):
        self._parser   = CommandParser()
        self._detector = IntentDetector()
        self._fallback = FallbackHandler()
        self._threshold = confidence_threshold

        # ── Handler registry ──────────────────────────────────
        # Maps intent name → handler instance
        self._handlers: Dict[str, BaseIntentHandler] = {
            INTENT_APP_CONTROL:     AppControlHandler(),
            INTENT_SYSTEM_CONTROL:  SystemControlHandler(),
            INTENT_MEDIA_CONTROL:   MediaControlHandler(),
            INTENT_WEB_SEARCH:      WebSearchHandler(),
            INTENT_UTILITY:         UtilityHandler(),
            INTENT_QUESTION_ANSWER: QuestionAnswerHandler(),
            INTENT_MEMORY:          MemoryHandler(),
            INTENT_UNKNOWN:         UnknownHandler(),
        }

        log.info(
            f"🔀 RoutingEngine initialized | "
            f"handlers={list(self._handlers.keys())} | "
            f"threshold={self._threshold}"
        )

    def register_handler(self, intent: str, handler: BaseIntentHandler) -> None:
        """
        Register a custom handler for an intent.
        Allows external plugins to extend routing.
        """
        self._handlers[intent] = handler
        log.info(f"Custom handler registered: [{intent}] → {type(handler).__name__}")

    async def route(
        self,
        raw_input: str,
        *,
        user_id: str = "unknown",
        session_id: Optional[str] = None,
    ) -> RouteResult:
        """
        Main entry point — route a raw text command end-to-end.
        Never raises. Always returns a RouteResult.
        """
        # Log the incoming command and obtain a correlation id
        request_id = elog.command(
            raw_input,
            user_id=user_id,
            session_id=session_id,
        )
        try:
            async with elog.async_timed(
                "routing_pipeline",
                request_id=request_id,
                user_id=user_id,
            ):
                result = await self._pipeline(raw_input, request_id=request_id)
            result.request_id = request_id  # propagate for callers
            return result
        except Exception as e:
            elog.failure(
                "routing_pipeline_error",
                str(e),
                service="routing_engine",
                request_id=request_id,
                user_id=user_id,
                exception=e,
            )
            log.error(f"RoutingEngine pipeline error: {e}", exc_info=True)
            return RouteResult(
                status="error",
                intent=INTENT_UNKNOWN,
                sub_intent=None,
                confidence=0.0,
                response="Something went wrong processing your command.",
                input_raw=raw_input,
                input_normalized="",
            )

    async def _pipeline(self, raw_input: str, *, request_id: Optional[str] = None) -> RouteResult:
        """The actual parse → detect → dispatch pipeline."""

        # ── Step 1: Parse ─────────────────────────────────────
        with elog.timed("parse", request_id=request_id):
            cmd: ParsedCommand = self._parser.parse(raw_input)

        if not cmd.tokens:
            elog.warning(
                "empty_command",
                "Received empty/unparseable command",
                request_id=request_id,
                service="routing_engine",
            )
            fb = await self._fallback.handle(cmd, reason="empty")
            return self._fallback_result(fb, cmd, [])

        # Update command log with parsed info
        elog.command(
            raw_input,
            normalized=cmd.normalized,
            tokens=cmd.tokens,
            entities=cmd.entities,
            request_id=request_id,
        )

        # ── Step 2: Detect intent ─────────────────────────────
        with elog.timed("intent_detection", request_id=request_id):
            all_results: List[IntentResult] = self._detector.detect_all(cmd)
        best: IntentResult = all_results[0]

        all_scores = [
            {"intent": r.intent, "confidence": round(r.confidence, 3)}
            for r in all_results
        ]

        # Log intent with structured event
        elog.intent(
            best.intent,
            best.confidence,
            all_scores,
            sub_intent=best.sub_intent,
            request_id=request_id,
            matched_keywords=best.matched_keywords,
        )

        log.info(
            f"⚡ Route: '{cmd.normalized[:50]}' → "
            f"{best.intent}({best.confidence:.2f})"
        )

        # ── Step 3: Confidence check ──────────────────────────
        if best.confidence < self._threshold:
            reason = "low_confidence" if best.confidence > 0.0 else "unknown"
            elog.warning(
                "low_confidence_fallback",
                f"Intent confidence {best.confidence:.2f} below threshold "
                f"{self._threshold:.2f} — falling back",
                request_id=request_id,
                service="routing_engine",
                context={
                    "best_intent": best.intent,
                    "confidence": best.confidence,
                    "threshold": self._threshold,
                },
            )
            fb = await self._fallback.handle(cmd, all_results, reason=reason)
            return self._fallback_result(fb, cmd, all_scores)

        # ── Step 4: Dispatch to handler ───────────────────────
        handler = self._handlers.get(best.intent, self._handlers[INTENT_UNKNOWN])
        with elog.timed(f"handler.{best.intent}", request_id=request_id, intent=best.intent):
            handler_response = await handler.handle(cmd, best)

        return RouteResult(
            status=handler_response.get("status", "ok"),
            intent=best.intent,
            sub_intent=best.sub_intent,
            confidence=best.confidence,
            response=handler_response.get("response", ""),
            input_raw=raw_input,
            input_normalized=cmd.normalized,
            handler_data=handler_response.get("data", {}),
            all_scores=all_scores,
            entities=cmd.entities,
        )

    def _fallback_result(
        self,
        fb: dict,
        cmd: ParsedCommand,
        all_scores: List[dict],
    ) -> RouteResult:
        return RouteResult(
            status="fallback",
            intent=INTENT_UNKNOWN,
            sub_intent=None,
            confidence=fb.get("confidence", 0.0),
            response=fb.get("response", ""),
            input_raw=cmd.raw,
            input_normalized=cmd.normalized,
            all_scores=all_scores,
            entities=cmd.entities,
        )

    def list_handlers(self) -> List[str]:
        return list(self._handlers.keys())


__all__ = ["RoutingEngine", "RouteResult"]
