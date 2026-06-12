# ============================================================
# GINI-ORACLE-1 — Intent Dispatch Layer
# assistant_core/intent_dispatch.py
# ============================================================
"""
GINI INTELLIGENCE ENGINE
=========================
Every user message is processed strictly through the primary AI engine.
No local fallback responses (mock/hardcoded) are permitted to answer user queries.
If the API fails, a strict visible error is returned to the user.

Diagnostics logged for every request:
  [API CALL VERIFICATION] PRE-FLIGHT
  [API CALL VERIFICATION] REQUEST SENT
  [API CALL VERIFICATION] RESPONSE RECEIVED
  [API CALL VERIFICATION] FAILED
"""

import re
from typing import Optional

from utils.logger import get_logger
from config.settings import settings
from assistant_core.ai_provider import get_ai_provider
from assistant_core.identity import IdentityManager

log = get_logger(__name__)

_HARD_ERROR = (
    "Unable to reach the AI provider. Please check your network connection or API configuration."
)

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
    Gini Intelligence Engine dispatch: processes every message through the primary engine.
    Strictly prohibits silent fallbacks. If API fails, returns an explicit error message.
    """
    history = history or []
    text = user_input.strip()

    # ── DIAGNOSTIC: CHAT RECEIVED ─────────────────────────────
    log.info(f"[CHAT RECEIVED] user_id={user_id} | message='{text[:80]}{'...' if len(text) > 80 else ''}'")

    api_key = (settings.api_key or "").strip().strip("[]")
    provider_name = (settings.ai_provider or "").strip().strip("[]").lower()

    if not api_key:
        log.error("[API CALL VERIFICATION] FAILED: No API Key configured.")
        return "I am not fully configured. The AI provider API key is missing."

    try:
        # Build system instruction
        memories = {}
        if memory:
            try:
                active_topic = memory.get_active_topic(session_id) if session_id else None
                memories = memory.get_relevant_memories(user_id, text, active_topic=active_topic)
            except Exception as mem_err:
                log.warning(f"[MEMORY] Memory retrieval failed (non-critical): {mem_err}")

        system_instruction = IdentityManager.get_system_instruction(memories)

        # Build cleaned history for API (last 10 turns to keep tokens low)
        cleaned_history = []
        for turn in history[-10:]:
            role = turn.get("role")
            if role in ("user", "assistant", "model"):
                cleaned_history.append({
                    "role": "user" if role == "user" else "assistant",
                    "content": turn.get("content", ""),
                })

        # ── API CALL VERIFICATION: PRE-FLIGHT ─────────────────
        log.info(f"[API CALL VERIFICATION] PRE-FLIGHT: Preparing to call {provider_name} with model {settings.model_name}")

        ai_provider = get_ai_provider()

        # ── API CALL VERIFICATION: REQUEST SENT ───────────────
        log.info(f"[API CALL VERIFICATION] REQUEST SENT: Prompt Length: {len(text)}, History Turns: {len(cleaned_history)}")

        ai_response = await ai_provider.generate_response(
            prompt=text,
            system_instruction=system_instruction,
            history=cleaned_history,
        )

        if ai_response and ai_response.strip():
            # ── API CALL VERIFICATION: RESPONSE RECEIVED ──────
            log.info(f"[API CALL VERIFICATION] RESPONSE RECEIVED: Length: {len(ai_response)} chars.")

            response = _apply_emotion_tone(ai_response.strip(), emotion, emotion_trend)

            # ── DIAGNOSTIC: RESPONSE RETURNED TO FRONTEND ─
            log.info(f"[RESPONSE RETURNED TO FRONTEND] user_id={user_id} | source=AI_Provider | len={len(response)} chars")
            return response

        else:
            log.warning("[API CALL VERIFICATION] FAILED: Provider returned an empty string.")
            return _HARD_ERROR

    except Exception as e:
        # ── API CALL VERIFICATION: FAILED ─────────────────────
        error_str = str(e)
        _log_engine_failure(error_str)
        log.error(f"[API CALL VERIFICATION] FAILED: Exception thrown during API call.")
        return _HARD_ERROR


def _log_engine_failure(error_str: str) -> None:
    """Log detailed engine failure diagnostics without exposing provider names."""
    error_lower = error_str.lower()

    if "timeout" in error_lower or "timed out" in error_lower:
        log.error(f"[ENGINE FAILURE] reason=TIMEOUT | detail='{error_str[:200]}'")
    elif "429" in error_str or "rate limit" in error_lower or "quota" in error_lower:
        log.error(f"[ENGINE FAILURE] reason=RATE_LIMIT | http_status=429 | detail='{error_str[:200]}'")
    elif "401" in error_str or "403" in error_str or "unauthorized" in error_lower or "forbidden" in error_lower:
        log.error(f"[ENGINE FAILURE] reason=AUTH_ERROR | http_status={'401' if '401' in error_str else '403'} | detail='{error_str[:200]}'")
    elif "network" in error_lower or "connection" in error_lower or "connect" in error_lower:
        log.error(f"[ENGINE FAILURE] reason=NETWORK_ERROR | detail='{error_str[:200]}'")
    else:
        import re as _re
        status_match = _re.search(r"\b(4\d{2}|5\d{2})\b", error_str)
        http_status = status_match.group(1) if status_match else "unknown"
        log.error(f"[ENGINE FAILURE] reason=ENGINE_ERROR | http_status={http_status} | detail='{error_str[:200]}'")


def _apply_emotion_tone(response: str, emotion: str, emotion_trend: str) -> str:
    """Prepend a brief empathetic prefix when the user is consistently negative."""
    if emotion_trend == "negative" and emotion == "negative":
        if not response.startswith("I understand") and not response.startswith("I'm here"):
            return "I understand, and I'm here for you. " + response
    return response


__all__ = ["dispatch"]
