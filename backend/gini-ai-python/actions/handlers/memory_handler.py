# actions/handlers/memory_handler.py
import re
from typing import Optional

from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult
from core.service_registry import get_registry


DEFAULT_PROFILE_USER = "default"


class MemoryHandler(BaseIntentHandler):
    intent_name = "memory"

    def __init__(self):
        super().__init__()
        self._memory = get_registry().resolve_optional("memory")

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        sub = result.sub_intent or "store"

        if sub == "store":
            return await self._handle_store(cmd)
        elif sub == "recall":
            return await self._handle_recall(cmd)
        elif sub == "forget":
            return await self._handle_forget(cmd)

        return self._ok("Memory command acknowledged.", sub=sub)

    async def _handle_store(self, cmd: ParsedCommand) -> dict:
        parsed = self._parse_memory_fact(cmd)
        if parsed:
            topic, value = parsed
            if self._memory:
                self._memory.remember_fact(DEFAULT_PROFILE_USER, topic, value)
            return self._ok(
                f"Got it! I'll remember: '{value}'.",
                sub="store",
                topic=topic,
                value=value,
            )

        return self._ok("What would you like me to remember?", sub="store")

    async def _handle_recall(self, cmd: ParsedCommand) -> dict:
        topic = self._extract_topic(cmd)
        if self._memory:
            facts = self._memory.recall_fact(DEFAULT_PROFILE_USER, topic if topic else None)
            if facts:
                if isinstance(facts, dict):
                    if len(facts) == 1:
                        topic_name, fact_value = next(iter(facts.items()))
                        if topic_name == "name":
                            return self._ok(
                                f"Your name is {fact_value}.",
                                sub="recall",
                                topic=topic_name,
                                value=fact_value,
                            )
                        return self._ok(
                            f"I remember {topic_name}: {fact_value}.",
                            sub="recall",
                            topic=topic_name,
                            value=fact_value,
                        )
                    items = ", ".join([f"{k}: {v}" for k, v in facts.items()])
                    return self._ok(
                        f"I remember several things: {items}.",
                        sub="recall",
                        facts=facts,
                    )
                if topic == "name":
                    return self._ok(
                        f"Your name is {facts}.",
                        sub="recall",
                        topic=topic,
                        value=facts,
                    )
                return self._ok(
                    f"I remember {topic}: {facts}.",
                    sub="recall",
                    topic=topic,
                    value=facts,
                )

            if topic:
                return self._ok(
                    f"I don't have anything stored for '{topic}'.",
                    sub="recall",
                    topic=topic,
                )
            return self._ok("I don't have any memories yet. What should I remember?", sub="recall")

        return self._ok(
            "Memory storage is not available right now.",
            sub="recall",
        )

    async def _handle_forget(self, cmd: ParsedCommand) -> dict:
        topic = self._extract_topic(cmd)
        if not topic:
            return self._ok("What should I forget?", sub="forget")

        if self._memory:
            deleted = self._memory.forget_fact(DEFAULT_PROFILE_USER, topic)
            if deleted:
                return self._ok(
                    f"I've forgotten '{topic}' from my memory.",
                    sub="forget",
                    topic=topic,
                )
            return self._ok(
                f"I couldn't find anything to forget for '{topic}'.",
                sub="forget",
                topic=topic,
            )

        return self._ok(
            "Memory storage is not available right now.",
            sub="forget",
        )

    def _parse_memory_fact(self, cmd: ParsedCommand) -> Optional[tuple[str, str]]:
        patterns = [
            (r"my\s+name\s+is\s+(.+)", "name"),
            (r"remember\s+that\s+(.+)", None),
            (r"note\s+that\s+(.+)", None),
            (r"keep\s+in\s+mind\s+(?:that\s+)?(.+)", None),
            (r"i\s+(?:like|love|prefer|hate)\s+(.+)", "preference"),
            (r"i\s+am\s+(?:a\s+)?(.+)", "profile"),
        ]

        for pattern, topic in patterns:
            match = re.search(pattern, cmd.raw, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if topic is None:
                    return (self._infer_topic(value.lower()), value)
                return (topic, value)
        return None

    def _infer_topic(self, text: str) -> str:
        if text.startswith("i like") or text.startswith("i love") or text.startswith("i prefer"):
            return "preference"
        if text.startswith("i hate"):
            return "preference"
        if text.startswith("my name is"):
            return "name"
        if "theme" in text or "color" in text or "music" in text:
            return "preference"
        return "note"

    def _extract_topic(self, cmd: ParsedCommand) -> str:
        patterns = [
            r"recall\s+(?:about\s+)?(.+)",
            r"remember\s+(?:about\s+)?(.+)",
            r"forget\s+(?:about\s+)?(.+)",
            r"what\s+do\s+you\s+know\s+about\s+(.+)",
            # Memory query patterns: "what is my name", "what's my X"
            r"what(?:\s+is|\s+am)?\s+(?:my|is|am)\s+(.+?)(?:\?)?$",
            r"whats?\s+(?:my|is|am)\s+(.+?)(?:\?)?$",
            r"who\s+(?:am\s+)?i(?:\?)?$",
            r"who\s+do\s+i\s+(.+?)(?:\?)?$",
        ]
        for pattern in patterns:
            match = re.search(pattern, cmd.normalized)
            if match:
                topic = match.group(1).strip() if match.lastindex else "name"
                return topic if topic else "name"
        return ""


__all__ = ["MemoryHandler"]
