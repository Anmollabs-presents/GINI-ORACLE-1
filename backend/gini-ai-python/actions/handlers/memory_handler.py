# actions/handlers/memory_handler.py
# ============================================================
# GINI-ORACLE-1 — Memory Intent Handler (V2)
# ============================================================
"""
Handles memory store / recall / forget intents.

V2 Changes:
  - Lazy registry resolve (fixes silent None-memory bug when
    MemoryHandler is constructed before MemoryManager is registered)
  - Explicit patterns for all 5 categories: personal, project,
    preference, task, fact
  - Natural recall responses ("Your name is X", "You are building X")
  - Overwrite acknowledgement ("Updated: ...")
  - Improved _extract_topic for "what is my name / color / project"
"""

import re
from typing import Optional

from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult
from core.service_registry import get_registry
from utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_PROFILE_USER = "default"


class MemoryHandler(BaseIntentHandler):
    intent_name = "memory"

    # ── Lazy memory property ──────────────────────────────────
    @property
    def _memory(self):
        """Resolve MemoryManager lazily from the registry each call.

        This avoids the bug where MemoryHandler is constructed inside
        RoutingEngine.__init__() *before* MemoryManager is registered
        into the ServiceRegistry, which caused self._memory to be None
        for the lifetime of the handler.
        """
        return get_registry().resolve_optional("memory")

    # ── Entry point ───────────────────────────────────────────

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        sub = result.sub_intent or "store"

        if sub == "store":
            return await self._handle_store(cmd)
        elif sub == "recall":
            return await self._handle_recall(cmd)
        elif sub == "forget":
            return await self._handle_forget(cmd)

        return self._ok("Memory command acknowledged.", sub=sub)

    # ── Store ─────────────────────────────────────────────────

    async def _handle_store(self, cmd: ParsedCommand) -> dict:
        parsed = self._parse_memory_fact(cmd)
        if parsed:
            topic, value, category = parsed

            # Check whether this is an overwrite
            is_update = False
            if self._memory:
                existing = self._memory.recall_fact(cmd.user_id, topic)
                is_update = bool(existing)
                self._memory.remember_fact(cmd.user_id, topic, value, category=category)

            verb = "Updated" if is_update else "Got it"
            return self._ok(
                f"{verb}! I'll remember: '{value}'.",
                sub="store",
                topic=topic,
                value=value,
                category=category,
                updated=is_update,
            )

        return self._ok("What would you like me to remember?", sub="store")

    # ── Recall ────────────────────────────────────────────────

    async def _handle_recall(self, cmd: ParsedCommand) -> dict:
        topic = self._extract_topic(cmd)

        if not self._memory:
            return self._ok("Memory storage is not available right now.", sub="recall")

        facts = self._memory.recall_fact(cmd.user_id, topic if topic else None)

        if facts:
            # Single string value
            if isinstance(facts, str):
                return self._ok(
                    self._format_recall(topic, facts),
                    sub="recall",
                    topic=topic,
                    value=facts,
                )

            # Dict of {topic: value}
            if isinstance(facts, dict):
                if len(facts) == 1:
                    t, v = next(iter(facts.items()))
                    return self._ok(
                        self._format_recall(t, v),
                        sub="recall",
                        topic=t,
                        value=v,
                    )
                items = "; ".join([f"{k}: {v}" for k, v in facts.items()])
                return self._ok(
                    f"I remember several things about you: {items}.",
                    sub="recall",
                    facts=facts,
                )

        if topic:
            return self._ok(
                f"I don't have anything stored for '{topic}'. What should I remember?",
                sub="recall",
                topic=topic,
            )
        return self._ok(
            "I don't have any memories yet. What should I remember?",
            sub="recall",
        )

    # ── Forget ────────────────────────────────────────────────

    async def _handle_forget(self, cmd: ParsedCommand) -> dict:
        topic = self._extract_topic(cmd)
        if not topic:
            return self._ok("What should I forget?", sub="forget")

        if self._memory:
            deleted = self._memory.forget_fact(cmd.user_id, topic)
            if deleted:
                return self._ok(
                    f"Done — I've forgotten '{topic}' from my memory.",
                    sub="forget",
                    topic=topic,
                )
            return self._ok(
                f"I couldn't find anything to forget for '{topic}'.",
                sub="forget",
                topic=topic,
            )

        return self._ok("Memory storage is not available right now.", sub="forget")

    # ── Pattern matching for storing facts ───────────────────

    def _parse_memory_fact(self, cmd: ParsedCommand) -> Optional[tuple[str, str, Optional[str]]]:
        """
        Try each pattern in priority order.
        Returns (topic, value, category) or None.

        Priority:
          1. Exact personal / project / preference patterns (high specificity)
          2. Generic "remember that / note that / keep in mind" patterns
          3. Contextual "I am / I like / I hate" patterns
        """
        patterns = [
            # ── Personal ─────────────────────────────────────
            (r"(?:remember\s+(?:that\s+)?)?my\s+name\s+is\s+(.+)",
             "name", "personal"),

            # ── Project ──────────────────────────────────────
            (r"(?:remember\s+(?:that\s+)?)?i\s+am\s+building\s+(.+)",
             "project", "project"),
            (r"(?:remember\s+(?:that\s+)?)?i\s+am\s+working\s+on\s+(.+)",
             "project", "project"),
            (r"(?:remember\s+(?:that\s+)?)?i\s+(?:am\s+)?developing\s+(.+)",
             "project", "project"),

            # ── Preferences ──────────────────────────────────
            (r"(?:remember\s+(?:that\s+)?)?my\s+(?:favorite|favourite)\s+(?:color|colour)\s+is\s+(.+)",
             "favorite color", "preference"),
            (r"(?:remember\s+(?:that\s+)?)?my\s+(?:favorite|favourite)\s+(.+?)\s+is\s+(.+)",
             None, "preference"),   # generic "my favourite X is Y" — handled below
            (r"(?:remember\s+(?:that\s+)?)?i\s+(?:like|love|prefer)\s+(.+)",
             "preference", "preference"),
            (r"(?:remember\s+(?:that\s+)?)?i\s+hate\s+(.+)",
             "dislike", "preference"),

            # ── Generic remember patterns ─────────────────────
            (r"remember\s+that\s+(.+)", None, None),
            (r"note\s+that\s+(.+)", None, None),
            (r"keep\s+in\s+mind\s+(?:that\s+)?(.+)", None, None),
            (r"don'?t\s+forget\s+(?:that\s+)?(.+)", None, None),

            # ── Identity / profile ────────────────────────────
            (r"i\s+am\s+(?:a\s+|an\s+)?(.+)", "profile", "personal"),
        ]

        for pattern, topic, category in patterns:
            match = re.search(pattern, cmd.raw, flags=re.IGNORECASE)
            if not match:
                continue

            # Special case: "my favourite X is Y" with two capture groups
            if topic is None and match.lastindex and match.lastindex >= 2:
                try:
                    fav_topic = f"favorite {match.group(1).strip().lower()}"
                    value = match.group(2).strip()
                    return (fav_topic, value, category)
                except IndexError:
                    pass

            value = match.group(1).strip() if match.lastindex else ""
            if not value:
                continue

            if topic is None:
                inferred_topic = self._infer_topic(value.lower())
                return (inferred_topic, value, None)
            return (topic, value, category)

        return None

    def _infer_topic(self, text: str) -> str:
        """Infer a topic label from the remembered value text."""
        t = text.lower()
        if "my name is" in t or t.startswith("name"):
            return "name"
        if "favorite" in t or "favourite" in t:
            if "color" in t or "colour" in t:
                return "favorite color"
            return "favorite"
        if "building" in t or "working on" in t or "project" in t or "developing" in t:
            return "project"
        if "like" in t or "love" in t or "prefer" in t or "hate" in t:
            return "preference"
        if "task" in t or "todo" in t or "reminder" in t or "deadline" in t:
            return "task"
        return "note"

    # ── Recall topic extraction ───────────────────────────────

    def _extract_topic(self, cmd: ParsedCommand) -> str:
        """
        Extract the topic being recalled.
        Handles: "what is my name", "what's my favorite color",
                 "what project am I building", "who am I", etc.
        """
        raw = cmd.raw.strip()

        # Hardcoded high-priority patterns (order matters)
        priority = [
            (r"what\s+(?:is|'?s)\s+my\s+(?:favorite|favourite)\s+(color|colour)",
             "favorite color"),
            (r"what\s+(?:project|app|thing)\s+am\s+i\s+(?:building|working\s+on|developing|doing)",
             "project"),
            (r"what\s+am\s+i\s+(?:building|working\s+on|developing)",
             "project"),
            (r"what\s+is\s+my\s+project",
             "project"),
            (r"what\s+is\s+my\s+name",
             "name"),
            (r"what\s+'?s\s+my\s+name",
             "name"),
            (r"who\s+am\s+i",
             "name"),
        ]
        for pattern, fixed_topic in priority:
            if re.search(pattern, raw, re.IGNORECASE):
                return fixed_topic

        # Dynamic extraction: "what is my X" / "what's my X"
        dynamic = [
            r"what\s+(?:is|are|'?s)\s+my\s+(.+?)(?:\?)?$",
            r"recall\s+(?:about\s+)?(.+)",
            r"do\s+you\s+(?:remember|know)\s+(?:my\s+)?(.+?)(?:\?)?$",
            r"forget\s+(?:about\s+)?(.+)",
            r"what\s+do\s+you\s+know\s+about\s+(?:my\s+)?(.+?)(?:\?)?$",
        ]
        for pattern in dynamic:
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                topic = match.group(1).strip().rstrip("?").strip()
                return topic if topic else ""

        return ""

    # ── Natural recall response formatting ───────────────────

    def _format_recall(self, topic: str, value: str) -> str:
        """Return a natural-language recall response."""
        t = (topic or "").lower().strip()

        if t in ("name", "my name"):
            return f"Your name is {value}."
        if t in ("project", "project name"):
            return f"You are building {value}."
        if t in ("favorite color", "favourite color", "color", "colour"):
            return f"Your favorite color is {value}."
        if "favorite" in t or "favourite" in t:
            what = t.replace("favorite", "").replace("favourite", "").strip()
            prefix = f"Your favorite {what}" if what else "Your favorite"
            return f"{prefix} is {value}."
        if t in ("profile", "i am", "who am i"):
            return f"You are {value}."
        if t in ("preference",):
            return f"I remember you prefer {value}."

        # Generic
        return f"I remember {topic}: {value}."


__all__ = ["MemoryHandler"]
