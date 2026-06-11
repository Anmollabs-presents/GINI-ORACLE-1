# actions/handlers/unknown_handler.py
from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult


class UnknownHandler(BaseIntentHandler):
    intent_name = "unknown"

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        return self._ok(
            "I'm not sure how to help with that yet. Try asking me to "
            "play music, search the web, set a timer, or control your devices.",
            sub="unknown",
        )


__all__ = ["UnknownHandler"]
