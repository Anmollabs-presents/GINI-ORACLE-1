# ============================================================
# GINI-ORACLE-1 — Base Intent Handler
# actions/handlers/base.py
# ============================================================

from abc import ABC, abstractmethod
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult
from utils.logger import get_logger


class BaseIntentHandler(ABC):
    """
    Abstract base for all intent handlers.
    Every handler must implement: intent_name and handle().
    """

    intent_name: str = "base"

    def __init__(self):
        self.log = get_logger(f"handler.{self.intent_name}")

    @abstractmethod
    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        """
        Process the command and return a response dict.

        Returns:
            {
                "status":   "ok" | "error" | "partial",
                "intent":   str,
                "sub":      str | None,
                "response": str,        # Human-readable response
                "data":     dict,       # Any extra structured data
            }
        """

    def _ok(self, response: str, sub: str = None, **data) -> dict:
        return {
            "status": "ok",
            "intent": self.intent_name,
            "sub": sub,
            "response": response,
            "data": data,
        }

    def _error(self, response: str, reason: str = "") -> dict:
        return {
            "status": "error",
            "intent": self.intent_name,
            "sub": None,
            "response": response,
            "data": {"reason": reason},
        }


__all__ = ["BaseIntentHandler"]
