# ============================================================
# GINI-ORACLE-1 — Hindi/Hinglish Command Normalizer
# voice/hindi_normalizer.py
# ============================================================
"""
Post-processes recognized text to handle:
  - Hindi commands → English equivalents
  - Common Hindi-accent pronunciation variations
  - Hinglish (Hindi + English) mixed commands
  - Common Gini-specific wake phrases in Hindi

This runs AFTER speech recognition, before intent detection.
"""

import re
from typing import Tuple
from utils.logger import get_logger

log = get_logger(__name__)

# ── Hindi → English command map ───────────────────────────────
# Format: (hindi_pattern, english_replacement)
HINDI_COMMAND_MAP = [
    # ── Multi-word phrases FIRST (longer → shorter to prevent partial matches) ──

    # Volume
    (r"\bavaaz band karo\b",    "mute"),
    (r"\bavaaz kam karo\b",     "volume down"),
    (r"\bavaaz badhao\b",       "volume up"),
    (r"\bavaaz\b",              "volume"),

    # Lights/devices (multi-word first)
    (r"\bbatti band karo\b",    "turn off lights"),
    (r"\bbatti chalu karo\b",   "turn on lights"),
    (r"\bbatti\b",              "light"),

    # Music (multi-word first)
    (r"\bgaana bajao\b",        "play music"),
    (r"\bagla gaana\b",         "next song"),
    (r"\bpichla gaana\b",       "previous song"),
    (r"\bgaana\b",              "song"),
    (r"\bsangeet\b",            "music"),
    (r"\broko\b",               "pause"),
    (r"\bchalaao\b",            "play"),
    (r"\bbajao\b",              "play"),

    # Control (multi-word first)
    (r"\bband karo\b",          "turn off"),
    (r"\bchalu karo\b",         "turn on"),
    (r"\bbandh karo\b",         "close"),
    (r"\bshuru karo\b",         "start"),
    (r"\bkholo\b",              "open"),
    (r"\bbandh\b",              "off"),
    (r"\bchalu\b",              "on"),

    # Single-word devices
    (r"\bpankha\b",             "fan"),
    (r"\bprakash\b",            "light"),
    (r"\bdarwaza\b",            "door"),
    (r"\bkhidki\b",             "window"),
    (r"\bghar\b",               "home"),

    # Time
    (r"\btimer lagao\b",        "set timer"),
    (r"\balarm lagao\b",        "set alarm"),
    (r"\byaad dilao\b",         "remind me"),
    (r"\bminute\b",             "minutes"),  # Common mispronunciation

    # Search
    (r"\bkhojna\b",             "search"),
    (r"\bdhoondho\b",           "find"),
    (r"\bbatao\b",              "tell me"),
    (r"\bkya hai\b",            "what is"),
    (r"\bkaun hai\b",           "who is"),
    (r"\bkahan hai\b",          "where is"),

    # Greetings / wake words
    (r"\bsuno gini\b",          "hey gini"),
    (r"\bgini suno\b",          "hey gini"),
    (r"\bthik hai\b",           "okay"),
    (r"\bshukriya\b",           "thank you"),
    (r"\bdhanyavad\b",          "thank you"),
]

# ── Pronunciation variations (accent normalization) ───────────
# Maps common Indian-accent speech-to-text errors → correct form
ACCENT_CORRECTIONS = [
    # W / V confusion
    (r"\bwolume\b",     "volume"),
    (r"\bwideo\b",      "video"),
    (r"\bwifi\b",       "wifi"),      # Usually fine but some engines mishear
    (r"\bwisit\b",      "visit"),

    # Th → D / T
    (r"\bde weather\b", "the weather"),
    (r"\bdis\b",        "this"),
    (r"\bdat\b",        "that"),
    (r"\bden\b",        "then"),

    # Number words
    (r"\bek\b",         "1"),
    (r"\bdo\b",         "2"),
    (r"\bteen\b",       "3"),
    (r"\bchar\b",       "4"),
    (r"\bpaanch\b",     "5"),
    (r"\bchhe\b",       "6"),
    (r"\bsaat\b",       "7"),
    (r"\baath\b",       "8"),
    (r"\bnau\b",        "9"),
    (r"\bdas\b",        "10"),

    # Common misrecognitions by Whisper for Indian accents
    (r"\bginny\b",      "gini"),
    (r"\bjeanie\b",     "gini"),
    (r"\bjanee\b",      "gini"),
    (r"\bgennie\b",     "gini"),
]

# ── Wake word variants ────────────────────────────────────────
WAKE_WORDS = {
    "hey gini", "hello gini", "gini", "ok gini", "okay gini",
    "suno gini", "gini suno", "aye gini", "hi gini",
}


class HindiNormalizer:
    """
    Post-processes raw STT output to normalize Hindi/Hinglish commands.
    Stateless — safe to reuse.
    """

    def normalize(self, text: str) -> Tuple[str, bool]:
        """
        Normalize text: apply Hindi→English map + accent corrections.

        Returns:
            (normalized_text, was_modified)
        """
        if not text:
            return text, False

        original = text
        result = text.lower().strip()

        # Apply Hindi command translations
        for pattern, replacement in HINDI_COMMAND_MAP:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # Apply accent corrections
        for pattern, replacement in ACCENT_CORRECTIONS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # Clean up multiple spaces
        result = re.sub(r"\s+", " ", result).strip()

        was_modified = result != original.lower().strip()
        if was_modified:
            log.debug(f"Normalized: '{original}' → '{result}'")

        return result, was_modified

    def strip_wake_word(self, text: str) -> Tuple[str, bool]:
        """
        Remove wake word from the beginning of a command.

        Returns:
            (text_without_wake_word, wake_word_found)
        """
        text_lower = text.lower().strip()

        for wake in sorted(WAKE_WORDS, key=len, reverse=True):
            if text_lower.startswith(wake):
                stripped = text[len(wake):].strip(" ,.")
                log.debug(f"Wake word '{wake}' stripped")
                return stripped, True

        return text, False

    def process(self, text: str) -> dict:
        """
        Full normalization pipeline.
        Returns dict with all processing results.
        """
        # Step 1: Strip wake word
        without_wake, had_wake = self.strip_wake_word(text)

        # Step 2: Hindi → English normalization
        normalized, was_translated = self.normalize(without_wake)

        return {
            "original":       text,
            "final":          normalized,
            "had_wake_word":  had_wake,
            "was_translated": was_translated,
        }

    def is_wake_word_only(self, text: str) -> bool:
        """Check if text is ONLY a wake word (no actual command)."""
        _, had_wake = self.strip_wake_word(text)
        stripped, _ = self.strip_wake_word(text)
        return had_wake and not stripped.strip()


__all__ = ["HindiNormalizer", "WAKE_WORDS", "HINDI_COMMAND_MAP"]
