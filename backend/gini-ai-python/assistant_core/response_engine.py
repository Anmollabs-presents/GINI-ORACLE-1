# ============================================================
# GINI-ORACLE-1 — Local Response Engine
# assistant_core/response_engine.py
# ============================================================
"""
Rule-based response engine. Handles:
  - Greetings and small talk
  - Identity questions ("who are you")
  - Capability questions ("what can you do")
  - Emotional support ("how are you", "are you okay")
  - Time / date queries (fast path before routing engine)
  - Math expressions
  - Memory store / recall (fast path)
  - Fallback for unmatched input

This module is purely local — no network calls, no API keys.
It runs in microseconds and never fails due to external dependencies.
"""

import re
import random
from datetime import datetime, timezone
from typing import Optional

from utils.logger import get_logger

log = get_logger(__name__)


# ── Response pools (varied so Gini doesn't sound robotic) ────

_GREETINGS = [
    "Hey! I'm Gini. How can I help you today?",
    "Hello! What can I do for you?",
    "Hi there! Ready to assist.",
    "Hey! Great to hear from you. What do you need?",
    "Hello! I'm Gini, your local AI assistant. Ask me anything.",
]

_HOW_ARE_YOU = [
    "I'm running great, thanks for asking! What can I help with?",
    "All systems operational! How about you?",
    "Doing well! I'm here whenever you need me.",
    "Running smoothly. What's on your mind?",
]

_WHAT_CAN_YOU_DO = """I can help you with quite a lot:

• **Commands** — open apps, control system volume, brightness, media playback
• **Web search** — search Google, YouTube, Wikipedia, maps, weather, news
• **Utilities** — set timers, alarms, reminders, calculate math
• **Memory** — remember facts about you, recall them later
• **Questions** — science, programming, general knowledge
• **Small talk** — I'm always here to chat

All of this works completely offline — no internet or API keys needed for most features. Just ask!"""

_IDENTITY = [
    "I'm Gini — your local, offline-first AI assistant. I run entirely on your device.",
    "I'm Gini! A locally-powered AI assistant. No cloud, no API keys, just local intelligence.",
    "Gini here — an offline AI assistant built to control your system, answer questions, and help you get things done.",
]

_THANKS = [
    "You're welcome! Anything else I can help with?",
    "Happy to help! Let me know if you need anything else.",
    "Anytime! What else can I do for you?",
    "Glad I could help!",
]

_GOODBYE = [
    "Goodbye! Have a great day.",
    "See you later! I'll be here when you need me.",
    "Take care! Come back anytime.",
]

_FALLBACK = [
    "I'm not sure how to respond to that. Try asking me to open an app, search the web, set a timer, or ask a question.",
    "Hmm, I didn't quite get that. I can help with app control, web search, timers, calculations, and general knowledge.",
    "I'm still learning! Try: 'open calculator', 'what is photosynthesis', or 'set a timer for 5 minutes'.",
    "Could you rephrase that? I work best with commands like 'search for...', 'open...', or 'what is...'",
]

# ── Intent patterns for the response engine ──────────────────

_PATTERNS = [
    # Greetings
    (r"^(hello|hi|hey|howdy|sup|what'?s up|greetings|good (morning|afternoon|evening|night))[\s!?.,]*$",
     "greeting"),
    # How are you
    (r"(how are you|how'?re you|you okay|you good|how do you feel|are you alright)",
     "how_are_you"),
    # Identity
    (r"(who are you|what are you|your name|what'?s your name|introduce yourself)",
     "identity"),
    # Capabilities
    (r"(what can you do|what do you do|your capabilities|help me|how can you help|what are your features)",
     "capabilities"),
    # Thanks
    (r"^(thank(s| you)|thx|ty|cheers|much appreciated|great job|good job|nice work)[\s!.,]*$",
     "thanks"),
    # Goodbye
    (r"^(bye|goodbye|see you|cya|see ya|later|take care|good night|gn)[\s!.,]*$",
     "goodbye"),
    # Affirmation
    (r"^(yes|yeah|yep|ok|okay|sure|alright|got it|understood|cool|great|perfect|awesome)[\s!.,]*$",
     "affirmation"),
    # Negation
    (r"^(no|nope|nah|never mind|never|cancel|stop|not now)[\s!.,]*$",
     "negation"),
]

_COMPILED = [(re.compile(p, re.IGNORECASE), intent) for p, intent in _PATTERNS]

# Math — only digits + operators, reject anything with words
_MATH_PATTERN = re.compile(
    r"^(?:calculate|calc|compute|what\s+is|whats)?\s*"
    r"([\d\s\+\-\*\/\.\(\)\%\^]+)$",
    re.IGNORECASE,
)

# Time / date
_TIME_PATTERN = re.compile(
    r"(what\s+time|current\s+time|time\s+is\s+it|time\s+now)", re.IGNORECASE
)
_DATE_PATTERN = re.compile(
    r"(what.*date|today.*date|date.*today|current\s+date|what\s+day)", re.IGNORECASE
)


class ResponseEngine:
    """
    Local rule-based response engine.
    Returns (response_text, handled: bool).
    If handled=False the caller should try other engines.
    """

    def generate(
        self,
        user_input: str,
        emotion: str = "neutral",
        emotion_trend: str = "neutral",
        memory=None,
        user_id: str = "default",
    ) -> tuple[str, bool]:
        """
        Try to generate a local response.

        Returns:
            (response_text, handled)
            handled=False means "I don't know — pass to next engine"
        """
        text = user_input.strip()
        lower = text.lower()

        # ── Time ─────────────────────────────────────────────
        if _TIME_PATTERN.search(lower):
            now = datetime.now()
            formatted = now.strftime("%I:%M %p").lstrip("0")
            return f"The current time is {formatted}.", True

        # ── Date ─────────────────────────────────────────────
        if _DATE_PATTERN.search(lower):
            today = datetime.now()
            formatted = today.strftime("%A, %B %d, %Y")
            return f"Today is {formatted}.", True

        # ── Math ─────────────────────────────────────────────
        math_result = self._try_math(text)
        if math_result is not None:
            return math_result, True

        # ── Pattern matching ──────────────────────────────────
        for pattern, intent in _COMPILED:
            if pattern.search(lower):
                response = self._handle_intent(intent, emotion, emotion_trend)
                if response:
                    return response, True

        return "", False

    def _try_math(self, text: str) -> Optional[str]:
        """Safely evaluate a math expression. Returns None if not math."""
        # Strip known prefixes
        cleaned = re.sub(
            r"^(calculate|calc|compute|what\s+is|whats)\s*", "", text,
            flags=re.IGNORECASE,
        ).strip()

        # Only allow safe math characters
        safe = re.sub(r"[^\d\s\+\-\*\/\.\(\)\%]", "", cleaned).strip()
        if not safe or len(safe) < 3:
            return None

        # Must contain at least one operator
        if not any(op in safe for op in ["+", "-", "*", "/", "%"]):
            return None

        try:
            result = eval(safe)  # noqa: S307 — safe: only digits+operators
            # Format nicely
            if isinstance(result, float) and result == int(result):
                result = int(result)
            return f"The result is **{result}**."
        except Exception:
            return None

    def _handle_intent(
        self, intent: str, emotion: str, emotion_trend: str
    ) -> Optional[str]:
        responses = {
            "greeting":     _GREETINGS,
            "how_are_you":  _HOW_ARE_YOU,
            "identity":     _IDENTITY,
            "thanks":       _THANKS,
            "goodbye":      _GOODBYE,
            "affirmation":  ["Got it!", "Understood!", "Sure thing!", "Okay!"],
            "negation":     ["Okay, no problem.", "Got it, I'll hold off.", "Sure, cancelled."],
        }
        if intent == "capabilities":
            return _WHAT_CAN_YOU_DO
        pool = responses.get(intent)
        if pool:
            # Vary with emotion-aware prefix occasionally
            response = random.choice(pool)
            if emotion == "negative" and intent in ("greeting", "how_are_you"):
                response = "I'm here for you. " + response
            return response
        return None


# Singleton
_engine: Optional[ResponseEngine] = None

def get_response_engine() -> ResponseEngine:
    global _engine
    if _engine is None:
        _engine = ResponseEngine()
    return _engine


__all__ = ["ResponseEngine", "get_response_engine"]
