# ============================================================
# GINI-ORACLE-1 — Intent Dispatch Layer
# assistant_core/intent_dispatch.py
# ============================================================
"""
The central orchestrator for Gini's local intelligence pipeline.

Decision pipeline for every incoming message:

  1. ResponseEngine     — greetings, small talk, time, date, math (~0ms)
  2. RoutingEngine      — commands: app launch, web search, system, media,
                          utility, memory, Q&A  (intent confidence ≥ 0.55)
  3. KnowledgeEngine    — factual questions the routing engine doesn't cover
  4. LocalLLM (opt.)    — richer answers if Ollama is running locally
  5. Fallback           — helpful "I don't know yet" message

No cloud APIs. No API keys. 100% offline.
"""

import re
from typing import Optional

from utils.logger import get_logger
from config.settings import settings
from assistant_core.response_engine import get_response_engine
from assistant_core.knowledge_engine import get_knowledge_engine
from assistant_core.local_llm_adapter import get_local_llm
from assistant_core.ai_provider import get_ai_provider
from assistant_core.identity import IdentityManager

log = get_logger(__name__)

# Questions that should go to the knowledge engine even if the
# routing engine scores them as question_answer (which doesn't have
# a rich local knowledge base in the handler itself).
_KNOWLEDGE_TRIGGERS = re.compile(
    r"(what\s+is|what\s+are|who\s+is|who\s+was|explain|define|"
    r"tell\s+me\s+about|describe|how\s+does|how\s+do|meaning\s+of)",
    re.IGNORECASE,
)

_COMMAND_INTENTS = {
    "app_control", "system_control", "media_control",
    "web_search", "utility", "memory",
}

_FALLBACK_RESPONSES = [
    "I don't have enough knowledge about that yet. "
    "Try asking me to open an app, search the web, set a timer, or ask about science or programming topics.",
    "Hmm, I'm not sure about that one. "
    "I can help with: app control, web search, timers, calculations, and general knowledge questions.",
    "I couldn't find an answer locally. "
    "If you have Ollama installed and LOCAL_LLM_ENABLED=true in your .env, "
    "I can use a local AI model to answer that.",
]
_fb_idx = 0


async def dispatch(
    user_input: str,
    emotion: str = "neutral",
    emotion_trend: str = "neutral",
    history: list = None,
    memory=None,
    user_id: str = "default",
    session_id: Optional[str] = None,
    routing_engine=None,
) -> str:
    """
    Central dispatch: route user_input through the local intelligence stack.
    Returns a response string — never raises.
    """
    global _fb_idx
    history = history or []
    text = user_input.strip()

    # ── STAGE 1: Rule-based response engine ──────────────────
    resp_engine = get_response_engine()
    response, handled = resp_engine.generate(
        text,
        emotion=emotion,
        emotion_trend=emotion_trend,
        memory=memory,
        user_id=user_id,
    )
    if handled and response:
        log.debug(f"ResponseEngine handled: '{text[:40]}'")
        return _apply_emotion_tone(response, emotion, emotion_trend)

    # ── STAGE 2: Routing engine (commands + memory actions) ─────
    intent = "unknown"
    confidence = 0.0
    routed_response = ""

    if routing_engine is not None:
        try:
            route_result = await routing_engine.route(
                text, user_id=user_id, session_id=session_id
            )
            intent = route_result.intent
            confidence = route_result.confidence
            routed_response = route_result.response

            # Command intents: always use the routing result if confidence is high
            if intent in _COMMAND_INTENTS and confidence >= 0.55:
                log.debug(f"RoutingEngine [{intent}@{confidence:.2f}] handled: '{text[:40]}'")
                return _apply_emotion_tone(routed_response, emotion, emotion_trend)

        except Exception as e:
            log.warning(f"RoutingEngine dispatch error: {e}")

    # ── STAGE 3: AI Reasoning Layer (with local fallback) ────
    use_ai = False
    provider_name = settings.ai_provider.lower()
    if provider_name in ("ollama", "local"):
        use_ai = True
    elif settings.api_key:
        use_ai = True

    if use_ai:
        try:
            # Check if we have an active topic in history
            active_topic = None
            if memory and session_id:
                active_topic = memory.get_active_topic(session_id)

            # Retrieve relevant memories
            memories = {}
            if memory:
                memories = memory.get_relevant_memories(user_id, text, active_topic=active_topic)

            # Generate system prompt instruction
            system_instruction = IdentityManager.get_system_instruction(memories)

            ai_provider = get_ai_provider()
            cleaned_history = []
            for turn in history:
                role = turn.get("role")
                if role in ("user", "assistant", "model"):
                    cleaned_history.append({
                        "role": "user" if role == "user" else "assistant",
                        "content": turn.get("content", "")
                    })

            ai_response = await ai_provider.generate_response(
                prompt=text,
                system_instruction=system_instruction,
                history=cleaned_history,
            )
            if ai_response:
                log.info(f"AI Provider ({settings.ai_provider}) successfully generated response.")
                return _apply_emotion_tone(ai_response, emotion, emotion_trend)
        except Exception as e:
            log.warning(f"AI Provider failed: {e}. Falling back to local intelligence.")

    # ── STAGE 4: Local Factual/Knowledge Fallback ────────────
    # 1. Standalone Knowledge Engine
    know_answer, know_conf = get_knowledge_engine().query(text)
    if know_answer and know_conf >= 0.5:
        log.debug(f"KnowledgeEngine fallback answered [{know_conf:.2f}]: '{text[:40]}'")
        return _apply_emotion_tone(know_answer, emotion, emotion_trend)

    # 2. Q&A Handler from Routing Engine if available
    if routed_response and "[LLM" not in routed_response:
        log.debug("RoutingEngine Q&A Handler fallback used.")
        return _apply_emotion_tone(routed_response, emotion, emotion_trend)

    # ── STAGE 5: Hard Fallback ────────────────────────────────
    fb = _FALLBACK_RESPONSES[_fb_idx % len(_FALLBACK_RESPONSES)]
    _fb_idx += 1
    log.debug(f"Hard Fallback used for: '{text[:40]}'")
    return _apply_emotion_tone(fb, emotion, emotion_trend)


def _apply_emotion_tone(response: str, emotion: str, emotion_trend: str) -> str:
    """Prepend a brief empathetic prefix when the user is consistently negative."""
    if emotion_trend == "negative" and emotion == "negative":
        if not response.startswith("I understand") and not response.startswith("I'm here"):
            return "I understand, and I'm here for you. " + response
    return response


__all__ = ["dispatch"]
