# ============================================================
# GINI-ORACLE-1 — Command Parser
# actions/command_parser.py
# ============================================================
"""
Parses raw user input into a structured ParsedCommand object.

Responsibilities:
- Normalize text (lowercase, strip, collapse whitespace)
- Tokenize into words
- Extract key entities (numbers, device names, locations, URLs)
- Detect negation
- Detect question vs command form
- Output a clean ParsedCommand for the intent detector
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from utils.logger import get_logger

log = get_logger(__name__)

# ── Entity patterns ───────────────────────────────────────────
_PATTERNS = {
    "url":        re.compile(r"https?://\S+|www\.\S+"),
    "number":     re.compile(r"\b\d+(?:\.\d+)?\b"),
    "percentage": re.compile(r"\b\d+\s*%\b"),
    "time":       re.compile(r"\b(?:\d{1,2}:\d{2}(?:\s?[ap]m)?|\d{1,2}\s?(?:am|pm))\b", re.IGNORECASE),
    "volume":     re.compile(r"\b(?:volume|vol)\s*(\d+)\b", re.IGNORECASE),
    "brightness": re.compile(r"\b(?:brightness|bright)\s*(\d+)\b", re.IGNORECASE),
}

_NEGATION_WORDS = {"not", "don't", "dont", "no", "never", "stop", "cancel", "off"}

_QUESTION_STARTERS = {
    "what", "who", "where", "when", "why", "how", "is", "are",
    "can", "could", "should", "do", "does", "did", "will", "which",
}


@dataclass
class ParsedCommand:
    """Structured representation of a parsed user command."""
    raw: str                              # Original unmodified input
    normalized: str                       # Lowercased, stripped
    tokens: List[str]                     # Individual words
    is_question: bool = False             # "What is..." vs "Turn on..."
    has_negation: bool = False            # "don't open", "turn off"
    entities: Dict[str, Any] = field(default_factory=dict)   # Extracted entities
    char_count: int = 0
    word_count: int = 0
    user_id: str = "default"
    session_id: Optional[str] = None

    def has_any(self, *words: str) -> bool:
        """Check if any of the given words appear in tokens."""
        token_set = set(self.tokens)
        return any(w in token_set for w in words)

    def has_all(self, *words: str) -> bool:
        """Check if all of the given words appear in tokens."""
        token_set = set(self.tokens)
        return all(w in token_set for w in words)

    def contains(self, phrase: str) -> bool:
        """Check if phrase appears in normalized text."""
        return phrase in self.normalized

    def starts_with_any(self, *words: str) -> bool:
        """Check if the command starts with any of the given words."""
        return bool(self.tokens) and self.tokens[0] in words


class CommandParser:
    """
    Converts raw string input into a ParsedCommand.
    Stateless — safe to reuse across requests.
    """

    def parse(self, raw_input: str, user_id: str = "default", session_id: Optional[str] = None) -> ParsedCommand:
        """
        Main parse entry point.
        Returns a ParsedCommand even for empty/invalid input.
        """
        if not raw_input or not raw_input.strip():
            return self._empty_command(raw_input or "", user_id, session_id)

        # ── Normalize ─────────────────────────────────────────
        normalized = self._normalize(raw_input)

        # ── Tokenize ──────────────────────────────────────────
        tokens = normalized.split()

        # ── Detect question ───────────────────────────────────
        is_question = (
            bool(tokens) and tokens[0] in _QUESTION_STARTERS
        ) or normalized.endswith("?")

        # ── Detect negation ───────────────────────────────────
        has_negation = any(t in _NEGATION_WORDS for t in tokens)

        # ── Extract entities ──────────────────────────────────
        entities = self._extract_entities(normalized, raw_input)

        cmd = ParsedCommand(
            raw=raw_input,
            normalized=normalized,
            tokens=tokens,
            is_question=is_question,
            has_negation=has_negation,
            entities=entities,
            char_count=len(normalized),
            word_count=len(tokens),
            user_id=user_id,
            session_id=session_id,
        )

        log.debug(
            f"Parsed: '{normalized[:50]}' | "
            f"question={is_question} negation={has_negation} "
            f"entities={list(entities.keys())}"
        )
        return cmd

    # ── Private helpers ───────────────────────────────────────

    def _normalize(self, text: str) -> str:
        """Lowercase, strip, collapse whitespace, remove special chars."""
        text = text.lower().strip()
        text = re.sub(r"\s+", " ", text)           # collapse whitespace
        text = re.sub(r"[^\w\s%:./?&=#\+\-\*/() ]", "", text)  # keep useful chars
        return text

    def _extract_entities(self, normalized: str, raw: str) -> Dict[str, Any]:
        """Extract all recognizable entities from the text."""
        entities: Dict[str, Any] = {}

        for name, pattern in _PATTERNS.items():
            matches = pattern.findall(normalized)
            if matches:
                entities[name] = matches[0] if len(matches) == 1 else matches

        # Device names (common smart-home / Gini targets)
        devices = self._extract_devices(normalized)
        if devices:
            entities["devices"] = devices

        # Locations / rooms
        rooms = self._extract_rooms(normalized)
        if rooms:
            entities["room"] = rooms[0]

        return entities

    def _extract_devices(self, text: str) -> List[str]:
        device_words = {
            "light", "lights", "fan", "ac", "tv", "television",
            "heater", "speaker", "alarm", "camera", "door", "lock",
            "window", "curtain", "pump", "car", "vehicle",
        }
        return [t for t in text.split() if t in device_words]

    def _extract_rooms(self, text: str) -> List[str]:
        room_words = {
            "bedroom", "kitchen", "bathroom", "living room", "office",
            "garage", "hallway", "garden", "balcony", "basement",
        }
        found = []
        for room in room_words:
            if room in text:
                found.append(room)
        return found

    def _empty_command(self, raw: str, user_id: str = "default", session_id: Optional[str] = None) -> ParsedCommand:
        return ParsedCommand(
            raw=raw,
            normalized="",
            tokens=[],
            is_question=False,
            has_negation=False,
            entities={},
            char_count=0,
            word_count=0,
            user_id=user_id,
            session_id=session_id,
        )


__all__ = ["CommandParser", "ParsedCommand"]
