# ============================================================
# GINI-ORACLE-1 — Core Assistant (Upgraded)
# core/assistant.py
# ============================================================
"""
GiniAssistant — the central brain of Gini.ai.

Responsibilities:
- Receive and validate messages
- Detect emotion from text (VADER-enhanced, keyword fallback)
- Query memory for session context
- Run plugin hooks (allow override)
- Generate response via LOCAL intelligence stack (no cloud APIs)
- Write turn to memory
- Route actions via ActionRouter
- Expose lifecycle hooks (on_startup / on_shutdown)

Local intelligence pipeline (no API keys required):
  1. ResponseEngine  — greetings, small talk, time, date, math
  2. RoutingEngine   — app control, web search, system, media, utility, memory
  3. KnowledgeEngine — science, CS, programming, general facts
  4. LocalLLM        — optional Ollama adapter (disabled by default)
  5. Fallback        — helpful "I don't know yet" message

Accepts a ServiceRegistry to resolve dependencies —
no hard imports of services (decoupled architecture).
"""

import asyncio
from typing import Optional

from utils.logger import get_logger
from utils.event_logger import get_event_logger
from config.settings import settings
from core.service_registry import ServiceRegistry, get_registry
from assistant_core.intent_dispatch import dispatch as local_dispatch

log = get_logger(__name__)
elog = get_event_logger()


class GiniAssistant:
    """
    Emotion-aware AI assistant engine.
    Wired via ServiceRegistry — not tightly coupled to any service.
    """

    def __init__(self, registry: Optional[ServiceRegistry] = None):
        self._registry = registry or get_registry()
        self.name = settings.app_name
        self.version = settings.app_version
        self._running = False
        log.info(f"🧠 GiniAssistant created | v{self.version}")

    # ── Lifecycle Hooks ───────────────────────────────────────

    async def on_startup(self) -> None:
        """Called by LifecycleManager during startup."""
        self._running = True
        elog.lifecycle("assistant", "complete", component="GiniAssistant",
                       metadata={"emotion_engine": settings.emotion_engine_enabled})
        log.info(f"✅ GiniAssistant is ready | Emotion engine: {settings.emotion_engine_enabled}")

    async def on_shutdown(self) -> None:
        """Called by LifecycleManager during shutdown."""
        self._running = False
        elog.lifecycle("assistant", "shutdown", component="GiniAssistant")
        log.info("🛑 GiniAssistant shutting down...")

    # ── Main Processing Loop ──────────────────────────────────

    async def process_message(
        self,
        user_input: str,
        user_id: str = "default",
        session_id: Optional[str] = None,
    ) -> dict:
        """
        Main entry point for all incoming messages.

        Pipeline:
          1. Validate input
          2. Get/create session memory
          3. Detect emotion
          4. Run plugin hooks (allow override)
          5. Generate response
          6. Store turn in memory
          7. Return result

        Always returns a dict — never raises to caller.
        """
        try:
            async with elog.async_timed(
                "process_message",
                user_id=user_id,
            ):
                return await self._run_pipeline(user_input, user_id, session_id)
        except Exception as e:
            elog.failure(
                "pipeline_unhandled_error",
                str(e),
                service="assistant",
                user_id=user_id,
                exception=e,
                critical=True,
            )
            log.error(f"❌ Pipeline error for [{user_id}]: {e}", exc_info=True)
            return self._error_response(user_id, session_id, str(e))

    async def _run_pipeline(
        self,
        user_input: str,
        user_id: str,
        session_id: Optional[str],
    ) -> dict:
        """Core processing pipeline — exception safety handled by caller."""

        # ── 1. Validate ──────────────────────────────────────
        user_input = user_input.strip()
        if not user_input:
            return {
                "response": "I didn't catch that. Could you say it again?",
                "emotion": "neutral",
                "user_id": user_id,
                "session_id": session_id,
            }

        log.info(f"📩 [{user_id}] → {user_input[:80]}{'...' if len(user_input) > 80 else ''}")

        # ── 2. Memory — get or create session ────────────────
        memory = self._registry.resolve_optional("memory")
        session = None
        active_session_id = session_id

        if memory:
            session = memory.get_or_create_session(user_id, session_id)
            active_session_id = session.session_id
            memory.add_turn(active_session_id, role="user", content=user_input)
            history = memory.get_history(active_session_id)
            emotion_trend = memory.get_emotion_trend(active_session_id)
        else:
            history = []
            emotion_trend = "neutral"

        # ── 3. Emotion Detection ──────────────────────────────
        emotion = self._detect_emotion(user_input)
        log.debug(f"Emotion detected: {emotion} | Trend: {emotion_trend}")

        # ── 4. Plugin hooks (may override response) ───────────
        plugin_manager = self._registry.resolve_optional("plugins")
        plugin_override = None

        if plugin_manager:
            from core.plugin_manager import PluginContext
            ctx = PluginContext(
                user_id=user_id,
                session_id=active_session_id or "",
                message=user_input,
                emotion=emotion,
                metadata={"emotion_trend": emotion_trend, "history_length": len(history)},
            )
            plugin_override = await plugin_manager.run_message_hooks(ctx)

        # ── 5. Generate Response ──────────────────────────────
        if plugin_override:
            response_text = plugin_override
            log.debug("Response provided by plugin override")
        else:
            response_text = await self._generate_response(
                user_input=user_input,
                emotion=emotion,
                emotion_trend=emotion_trend,
                history=history,
                user_id=user_id,
                session_id=active_session_id,
            )

        # ── 6. Store assistant turn in memory ─────────────────
        if memory and active_session_id:
            memory.add_turn(active_session_id, role="assistant", content=response_text, emotion=emotion)

        log.info(f"💬 [{user_id}] ← {response_text[:80]}{'...' if len(response_text) > 80 else ''}")

        return {
            "response": response_text,
            "emotion": emotion,
            "emotion_trend": emotion_trend,
            "user_id": user_id,
            "session_id": active_session_id,
        }

    # ── Response Generation ───────────────────────────────────

    async def _generate_response(
        self,
        user_input: str,
        emotion: str,
        emotion_trend: str,
        history: list,
        user_id: str = "default",
        session_id: Optional[str] = None,
    ) -> str:
        """
        Generate Gini's response via the LOCAL/AI hybrid intelligence stack.

        Pipeline:
          1. ResponseEngine  — greetings, small talk, time, date, math
          2. RoutingEngine   — commands (app, web, system, media, utility, memory)
          3. AI Provider     — general reasoning & knowledge using retrieved memories
          4. Fallbacks       — local knowledge database & fallback template
        """
        routing_engine = None
        action_router = self._registry.resolve_optional("action_router")
        if action_router and hasattr(action_router, "routing_engine"):
            routing_engine = action_router.routing_engine

        return await local_dispatch(
            user_input=user_input,
            emotion=emotion,
            emotion_trend=emotion_trend,
            history=history,
            memory=self._registry.resolve_optional("memory"),
            user_id=user_id,
            session_id=session_id,
            routing_engine=routing_engine,
        )

    # ── Emotion Detection ─────────────────────────────────────

    def _detect_emotion(self, text: str) -> str:
        """
        Detect emotion using VADER sentiment analysis (offline, no API).
        Falls back to keyword matching if vaderSentiment is unavailable.
        """
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            analyzer = SentimentIntensityAnalyzer()
            scores = analyzer.polarity_scores(text)
            compound = scores["compound"]
            if compound >= 0.20:
                return "positive"
            elif compound <= -0.20:
                return "negative"
            return "neutral"
        except ImportError:
            pass

        # Keyword fallback
        text_lower = text.lower()
        negative_words = {
            "sad", "upset", "angry", "frustrated", "hate", "terrible",
            "awful", "depressed", "unhappy", "miserable", "annoyed", "worried",
        }
        positive_words = {
            "happy", "great", "love", "excited", "amazing", "wonderful",
            "fantastic", "glad", "joyful", "excellent", "good", "awesome",
        }
        neg_score = sum(1 for w in negative_words if w in text_lower)
        pos_score = sum(1 for w in positive_words if w in text_lower)
        if neg_score > pos_score:
            return "negative"
        elif pos_score > neg_score:
            return "positive"
        return "neutral"

    # ── Action Execution ──────────────────────────────────────

    async def execute_action(self, intent: str, payload: dict) -> dict:
        """
        Execute a device/system action via ActionRouter.
        Runs plugin action hooks first.
        """
        plugin_manager = self._registry.resolve_optional("plugins")
        if plugin_manager:
            override = await plugin_manager.run_action_hooks(intent, payload)
            if override:
                return override

        action_router = self._registry.resolve_optional("action_router")
        if action_router:
            async with elog.async_timed(f"execute_action.{intent}", intent=intent):
                return await action_router.route(intent, payload)

        elog.warning(
            "no_action_router",
            f"No action router available for intent: {intent}",
            service="assistant",
            context={"intent": intent},
        )
        log.warning(f"No action router available for intent: {intent}")
        return {"status": "no_router", "intent": intent}

    # ── Helpers ───────────────────────────────────────────────

    def _error_response(self, user_id: str, session_id: Optional[str], error: str) -> dict:
        """Safe fallback response when pipeline errors occur."""
        return {
            "response": "Something went wrong on my end. Please try again.",
            "emotion": "neutral",
            "emotion_trend": "neutral",
            "user_id": user_id,
            "session_id": session_id,
            "error": error,
        }

    @property
    def is_running(self) -> bool:
        return self._running

    def status(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "running": self._running,
            "services": list(self._registry.list_services().keys()),
        }


__all__ = ["GiniAssistant"]
