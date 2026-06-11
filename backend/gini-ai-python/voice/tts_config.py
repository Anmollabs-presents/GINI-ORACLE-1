# ============================================================
# GINI-ORACLE-1 — TTS Configuration
# voice/tts_config.py
# ============================================================
"""
All TTS settings in one place.
Mirrors AudioConfig pattern from the STT subsystem.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class TTSBackend(str, Enum):
    PYTTSX3 = "pyttsx3"    # Offline, cross-platform, zero internet
    GTTS    = "gtts"       # Online, Google TTS, high quality
    ESPEAK  = "espeak"     # Offline, lightweight, Linux/Mac system tool
    MOCK    = "mock"       # Testing — generates real WAV via numpy


class VoiceGender(str, Enum):
    MALE   = "male"
    FEMALE = "female"
    NEUTRAL= "neutral"


class TTSLanguage(str, Enum):
    ENGLISH       = "en"
    HINDI         = "hi"
    HINDI_ENGLISH = "hi-en"   # Auto-select English voice with Hinglish awareness


@dataclass
class TTSConfig:
    """Complete configuration for speech output."""

    # ── Backend ───────────────────────────────────────────────
    backend: TTSBackend = TTSBackend.PYTTSX3
    fallback_backend: TTSBackend = TTSBackend.MOCK

    # ── Voice settings ────────────────────────────────────────
    language: TTSLanguage = TTSLanguage.ENGLISH
    gender: VoiceGender = VoiceGender.FEMALE
    voice_id: Optional[str] = None          # Specific voice ID (pyttsx3)
    preferred_voice_name: Optional[str] = None  # e.g. "Zira", "David", "Rishi"

    # ── Speech parameters ─────────────────────────────────────
    rate: int = 175                         # Words per minute (pyttsx3: 100-300)
    volume: float = 1.0                     # 0.0 – 1.0
    pitch: float = 1.0                      # Relative pitch (1.0 = normal)

    # ── Queue settings ────────────────────────────────────────
    queue_maxsize: int = 20                 # Max items in speech queue
    queue_timeout: float = 0.1             # Queue put/get timeout (seconds)

    # ── Interruption ─────────────────────────────────────────
    allow_interrupt: bool = True            # Allow stop mid-sentence
    interrupt_fade_ms: int = 50            # Fade-out time on interrupt (ms)

    # ── Output ────────────────────────────────────────────────
    output_device: Optional[int] = None    # None = system default
    save_to_file: bool = False             # Save audio to file as well
    output_dir: str = "logs/tts_output"   # Where to save audio files

    # ── Pre/post processing ───────────────────────────────────
    add_punctuation_pauses: bool = True    # Add natural pauses at punctuation
    max_chunk_length: int = 200            # Split long text into chunks (chars)
    sentence_pause_ms: int = 300          # Pause between sentences (ms)

    # ── Gini personality phrases ──────────────────────────────
    thinking_phrases: List[str] = field(default_factory=lambda: [
        "Let me check that for you.",
        "One moment.",
        "Sure, on it.",
        "Got it.",
    ])
    error_phrases: List[str] = field(default_factory=lambda: [
        "Sorry, I didn't catch that.",
        "I'm having trouble with that right now.",
        "Could you repeat that?",
    ])

    @classmethod
    def for_testing(cls) -> "TTSConfig":
        return cls(
            backend=TTSBackend.MOCK,
            rate=200,
            queue_maxsize=5,
        )

    @classmethod
    def for_pyttsx3(cls, gender: VoiceGender = VoiceGender.FEMALE) -> "TTSConfig":
        return cls(backend=TTSBackend.PYTTSX3, gender=gender)

    @classmethod
    def for_gtts(cls, language: TTSLanguage = TTSLanguage.ENGLISH) -> "TTSConfig":
        return cls(backend=TTSBackend.GTTS, language=language)


__all__ = ["TTSConfig", "TTSBackend", "VoiceGender", "TTSLanguage"]
