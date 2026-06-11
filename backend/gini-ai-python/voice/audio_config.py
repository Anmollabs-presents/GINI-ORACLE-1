# ============================================================
# GINI-ORACLE-1 — Audio Configuration
# voice/audio_config.py
# ============================================================
"""
Centralized audio configuration for the entire voice pipeline.
All tunable parameters in one place.
"""

from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class SampleRate(int, Enum):
    LOW    = 8000    # Minimum for speech
    MEDIUM = 16000   # Whisper/Vosk preferred
    HIGH   = 44100   # CD quality


class AudioBackend(str, Enum):
    WHISPER  = "whisper"    # OpenAI Whisper (local, offline)
    VOSK     = "vosk"       # Vosk (lightweight, offline)
    MOCK     = "mock"       # Testing / CI environments


class Language(str, Enum):
    ENGLISH       = "en"
    HINDI         = "hi"
    HINDI_ENGLISH = "hi-en"   # Hinglish / Hindi-accent English


@dataclass
class AudioConfig:
    """
    Complete configuration for audio capture and recognition.
    Designed for offline-first, Hindi-accent English support.
    """

    # ── Backend ───────────────────────────────────────────────
    backend: AudioBackend = AudioBackend.WHISPER
    fallback_backend: AudioBackend = AudioBackend.VOSK

    # ── Sample settings ───────────────────────────────────────
    sample_rate: int = SampleRate.MEDIUM          # 16kHz — Whisper/Vosk optimum
    channels: int = 1                             # Mono for speech
    chunk_size: int = 1024                        # Frames per buffer read
    sample_width: int = 2                         # 16-bit audio

    # ── Language ──────────────────────────────────────────────
    language: Language = Language.HINDI_ENGLISH
    whisper_model: str = "base"                   # tiny|base|small|medium|large

    # ── Capture timing ────────────────────────────────────────
    listen_timeout: float = 10.0                  # Max seconds to wait for speech start
    phrase_timeout: float = 8.0                   # Max seconds for a single phrase
    pause_threshold: float = 0.8                  # Silence seconds to end phrase
    phrase_min_duration: float = 0.3              # Ignore phrases shorter than this

    # ── Silence / noise detection ─────────────────────────────
    energy_threshold: int = 300                   # RMS energy threshold for speech
    dynamic_energy: bool = True                   # Auto-adjust energy threshold
    dynamic_energy_ratio: float = 1.5             # Adjustment sensitivity
    ambient_noise_duration: float = 1.0           # Seconds to sample ambient noise

    # ── Preprocessing ─────────────────────────────────────────
    noise_reduction: bool = True                  # Apply spectral noise reduction
    normalize_audio: bool = True                  # Normalize volume
    high_pass_filter: bool = True                 # Remove low-frequency rumble

    # ── Retry / error handling ────────────────────────────────
    max_retries: int = 3                          # Retries on recognition failure
    retry_delay: float = 0.5                      # Seconds between retries

    # ── Device ───────────────────────────────────────────────
    device_index: Optional[int] = None            # None = system default
    preferred_device_name: Optional[str] = None   # e.g. "USB Microphone"

    # ── Hindi / Indic support ─────────────────────────────────
    hindi_keywords: List[str] = field(default_factory=lambda: [
        "gini", "suno", "band karo", "chalu karo", "volume",
        "music", "call", "timer", "alarm", "search karo",
        "ghar", "light", "fan", "AC", "darwaza",
    ])

    @classmethod
    def for_whisper(cls, model: str = "base") -> "AudioConfig":
        return cls(backend=AudioBackend.WHISPER, whisper_model=model)

    @classmethod
    def for_vosk(cls) -> "AudioConfig":
        return cls(backend=AudioBackend.VOSK, fallback_backend=AudioBackend.MOCK)

    @classmethod
    def for_testing(cls) -> "AudioConfig":
        return cls(
            backend=AudioBackend.MOCK,
            listen_timeout=2.0,
            phrase_timeout=2.0,
            max_retries=1,
        )
    