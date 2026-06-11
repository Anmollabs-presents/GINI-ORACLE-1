# ============================================================
# GINI-ORACLE-1 — Fallback Handler
# actions/fallback_handler.py
# ============================================================
"""
Handles commands that couldn't be routed confidently.
Provides graceful, helpful responses instead of silent failures.

Strategies:
- Low confidence → ask for clarification
- Empty input → prompt user
- Ambiguous → list possible intents
- Error → safe error message
"""

from typing import List, Optional
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult, CONFIDENCE_MEDIUM
from utils.logger import get_logger

log = get_logger(__name__)

# ── Fallback response templates ───────────────────────────────
_RESPONSES_UNCLEAR = [
    "I didn't quite catch that. Could you rephrase?",
    "Hmm, I'm not sure what you mean. Can you be more specific?",
    "I want to help, but I need a clearer command. Try something like 'play music' or 'search for news'.",
]

_RESPONSES_EMPTY = [
    "Go ahead — I'm listening.",
    "What would you like me to do?",
    "I'm here! What do you need?",
]

_RESPONSES_AMBIGUOUS = [
    "That could mean a few things. Did you want to:\n{suggestions}",
    "I'm not quite sure — could you be one of these?\n{suggestions}",
]

_RESPONSE_ERROR = "Something went wrong while processing your command. Please try again."


class FallbackHandler:
    """
    Handles intents that couldn't be confidently routed.
    Always returns a safe, user-friendly CommandResult.
    """

    def __init__(self):
        self._response_idx = 0   # Rotate through responses
        log.debug("FallbackHandler initialized")

    async def handle(
        self,
        cmd: ParsedCommand,
        top_results: Optional[List[IntentResult]] = None,
        reason: str = "unknown",
    ) -> dict:
        """
        Generate a fallback response.

        Args:
            cmd: The parsed command that failed routing
            top_results: All scored intent results (for ambiguous suggestions)
            reason: Why fallback was triggered (unknown | low_confidence | error | empty)

        Returns:
            A CommandResult dict
        """
        log.info(f"⚠️ Fallback triggered | reason={reason} | input='{cmd.normalized[:40]}'")

        if reason == "empty" or not cmd.tokens:
            response = self._cycle(_RESPONSES_EMPTY)

        elif reason == "ambiguous" and top_results:
            suggestions = self._build_suggestions(top_results)
            template = self._cycle(_RESPONSES_AMBIGUOUS)
            response = template.format(suggestions=suggestions)

        elif reason == "low_confidence" and top_results:
            best = top_results[0]
            response = (
                f"I think you might want '{best.intent.replace('_', ' ')}', "
                f"but I'm not confident. Could you clarify?"
            )

        elif reason == "error":
            response = _RESPONSE_ERROR

        else:
            response = self._cycle(_RESPONSES_UNCLEAR)

        return {
            "status": "fallback",
            "intent": "unknown",
            "confidence": top_results[0].confidence if top_results else 0.0,
            "response": response,
            "reason": reason,
            "input": cmd.raw,
        }

    def _build_suggestions(self, results: List[IntentResult]) -> str:
        """Format top intent candidates as a suggestion list."""
        top = [r for r in results[:3] if r.confidence > 0.1]
        if not top:
            return "  • Something else entirely"
        lines = [
            f"  • {r.intent.replace('_', ' ').title()} "
            f"(e.g. '{self._example(r.intent)}')"
            for r in top
        ]
        return "\n".join(lines)

    def _example(self, intent: str) -> str:
        """Return a quick usage example for each intent."""
        examples = {
            "app_control":     "open Spotify",
            "system_control":  "turn volume up",
            "media_control":   "play next song",
            "web_search":      "search for today's news",
            "utility":         "set a 10 minute timer",
            "question_answer": "what is photosynthesis",
            "memory":          "remember I like dark mode",
            "unknown":         "...",
        }
        return examples.get(intent, "...")

    def _cycle(self, responses: List[str]) -> str:
        """Cycle through responses to avoid repetition."""
        response = responses[self._response_idx % len(responses)]
        self._response_idx += 1
        return response


__all__ = ["FallbackHandler"]
