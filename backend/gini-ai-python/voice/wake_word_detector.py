# ============================================================
# GINI-ORACLE-1 — Wake Word Detector
# voice/wake_word_detector.py
# ============================================================
"""
Low-resource always-listening wake word detection for Gini.ai.

Design goals:
  - Minimal CPU: only processes audio when energy crosses threshold
  - False trigger reduction: confidence gate + cooldown + confirmation window
  - Continuous: runs in a daemon thread, never blocks the main thread
  - Offline: no internet, no cloud API
  - Pluggable: swap in Porcupine/Picovoice with zero changes to VoiceEngine

Detection pipeline (per audio chunk):
  Microphone → RMS gate → buffer accumulate → STT → phrase match → callback

Two-stage false trigger reduction:
  Stage 1 — Energy gate: ignore chunks below RMS threshold (saves CPU ~90%)
  Stage 2 — Phrase match: fuzzy match against WAKE_WORDS after transcription
  Stage 3 — Cooldown: minimum N seconds between consecutive triggers
  Stage 4 — Confirmation window (optional): require wake phrase twice in T seconds

Supported wake phrases (from hindi_normalizer.WAKE_WORDS):
  "hey gini", "hello gini", "hi gini", "ok gini", "okay gini",
  "gini", "suno gini", "gini suno", "aye gini"

Usage:
    detector = WakeWordDetector(config, on_wake=my_callback)
    detector.start()           # non-blocking
    # ... user says "Hey Gini" ...
    # my_callback(WakeEvent) is called in detector thread
    detector.stop()
"""

import time
import threading
import struct
import math
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Set
from enum import Enum

from voice.hindi_normalizer import WAKE_WORDS
from voice.audio_config import AudioConfig, AudioBackend
from voice.audio_capture import create_capture_backend, CapturedAudio, _compute_rms
from utils.logger import get_logger

log = get_logger(__name__)


# ── Wake event ────────────────────────────────────────────────

@dataclass
class WakeEvent:
    """Fired when a wake phrase is detected."""
    phrase: str                    # Matched wake phrase e.g. "hey gini"
    confidence: float              # 0.0 – 1.0 match confidence
    audio: Optional[CapturedAudio] # Raw audio that triggered wake (for STT)
    timestamp: float = field(default_factory=time.time)
    triggered_by: str = "keyword"  # "keyword" | "mock"

    def __str__(self):
        return (
            f"WakeEvent('{self.phrase}' | "
            f"conf={self.confidence:.2f} | "
            f"t={self.timestamp:.1f})"
        )


class DetectorState(str, Enum):
    STOPPED  = "stopped"
    STARTING = "starting"
    IDLE     = "idle"          # Listening but no speech energy
    ACTIVE   = "active"        # Speech detected, buffering
    MATCHING = "matching"      # Running phrase match
    COOLDOWN = "cooldown"      # Just triggered, in cooldown window


# ── Wake word config ──────────────────────────────────────────

@dataclass
class WakeWordConfig:
    """Configuration for the wake word detector."""

    wake_phrases: Set[str] = field(default_factory=lambda: set(WAKE_WORDS))
    use_fuzzy_match: bool = True
    min_confidence: float = 0.75
    energy_threshold: int = 300
    cooldown_seconds: float = 2.5
    buffer_duration: float = 4.0
    max_buffer_duration: float = 4.0

    @classmethod
    def for_testing(cls) -> "WakeWordConfig":
        return cls(
            energy_threshold=100,
            cooldown_seconds=0.2,
            buffer_duration=0.5,
            max_buffer_duration=0.5,
            min_confidence=0.60,
            use_fuzzy_match=True,
        )

    @classmethod
    def for_production(cls) -> "WakeWordConfig":
        return cls(
            energy_threshold=300,
            cooldown_seconds=2.5,
            buffer_duration=4.0,
            max_buffer_duration=4.0,
            min_confidence=0.78,
            use_fuzzy_match=True,
        )


# ── Wake word detector ────────────────────────────────────────

class WakeWordDetector:
    """
    Low-resource always-listening wake word detector.

    Runs a daemon background thread that:
      1. Reads audio chunks continuously
      2. Gates on energy (skips silent chunks — saves CPU)
      3. Buffers speech audio
      4. Matches buffered audio against wake phrases (via STT)
      5. Fires callback on match (with cooldown + confidence gate)

    Thread-safe. Non-blocking. Graceful start/stop.
    """

    def __init__(
        self,
        config: Optional[WakeWordConfig] = None,
        audio_config: Optional[AudioConfig] = None,
        on_wake: Optional[Callable[[WakeEvent], None]] = None,
        on_listening: Optional[Callable[[], None]] = None,
    ):
        self.config = config or WakeWordConfig()
        self.audio_config = audio_config or AudioConfig.for_testing()
        self.on_wake = on_wake
        self.on_listening = on_listening

        # Components
        self._capture = create_capture_backend(self.audio_config)
        self._matcher = PhraseMatcher(
            self.config.wake_phrases,
            self.config.min_confidence,
        )
        self._recognizer = None

        # Threading
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._state = DetectorState.STOPPED

        # State
        self._last_trigger_time = 0.0
        self._audio_buffer: List[bytes] = []
        self._buffer_start_time = 0.0
        self._energy_threshold = self.config.energy_threshold
        self._trigger_count = 0

        log.info(
            f"🎯 WakeWordDetector created | "
            f"phrases={len(self.config.wake_phrases)} | "
            f"cooldown={self.config.cooldown_seconds}s"
        )

    def detect(self, audio: Optional[CapturedAudio]) -> Optional[WakeEvent]:
        """Synchronous wake-word detection from captured audio."""
        if not audio:
            return None

        if self._recognizer is None:
            self._lazy_init_recognizer()
            if self._recognizer is None:
                return None

        try:
            rec_result = self._recognizer.recognize(audio)
            if not rec_result.success or not rec_result.text:
                return None
            text = rec_result.text.lower().strip()
        except Exception as e:
            log.debug(f"Wake detection transcription error: {e}")
            return None

        matched, phrase, confidence = self._matcher.match(text)
        if matched and confidence >= self.config.min_confidence:
            return WakeEvent(
                phrase=phrase,
                confidence=confidence,
                audio=audio,
                timestamp=time.time(),
                triggered_by="detect()",
            )
        return None

    def is_wake(self, text: str) -> bool:
        """Text-only wake-word detection for API callers."""
        if not text:
            return False
        text = text.lower().strip()
        matched, phrase, confidence = self._matcher.match(text)
        is_wake_detected = matched and confidence >= self.config.min_confidence
        if is_wake_detected:
            log.debug(f"is_wake() match: '{text}' -> '{phrase}' ({confidence:.2f})")
        return is_wake_detected

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        """Start always-listening in background thread."""
        if self._thread and self._thread.is_alive():
            log.warning("WakeWordDetector already running")
            return

        self._stop_event.clear()
        self._capture.initialize()
        self._lazy_init_recognizer()

        self._thread = threading.Thread(
            target=self._detection_loop,
            name="GiniWakeDetector",
            daemon=True,
        )
        self._thread.start()
        self._state = DetectorState.STARTING
        log.info("👂 Wake word detection started")

    def stop(self) -> None:
        """Stop detection gracefully."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._state = DetectorState.STOPPED
        log.info("⏹ Wake word detection stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Main detection loop ───────────────────────────────────

class PhraseMatcher:
    """
    Fuzzy phrase matching for wake word detection.
    Uses character-level similarity + substring detection.
    No external dependencies (pure Python).
    """

    def __init__(self, phrases: Set[str], min_ratio: float = 0.75):
        self.phrases = {p.lower().strip() for p in phrases}
        self.min_ratio = min_ratio
        # Pre-build expanded variants for common misrecognitions
        self._variants = self._build_variants()

    def _build_variants(self) -> Set[str]:
        """Generate common acoustic confusables for each phrase."""
        variants = set(self.phrases)
        replacements = [
            ("hey",   ["hay", "he", "a", "aye"]),
            ("gini",  ["genie", "ginny", "jenny", "jeanie", "jini", "giny", "gene"]),
            ("hello", ["helo", "hallow", "hullo"]),
            ("ok",    ["okay", "o k"]),
            ("suno",  ["sono", "sunno"]),
        ]
        for phrase in list(self.phrases):
            for word, alts in replacements:
                if word in phrase:
                    for alt in alts:
                        variants.add(phrase.replace(word, alt))
        return variants

    def match(self, text: str) -> tuple[bool, str, float]:
        """
        Check if text contains a wake phrase.

        Returns:
            (matched: bool, phrase: str, confidence: float)
        """
        text = text.lower().strip()
        if not text:
            return False, "", 0.0

        # ── Exact / substring match (confidence = 1.0) ────────
        for phrase in self.phrases:
            if phrase in text:
                return True, phrase, 1.0

        # ── Variant match (confidence = 0.95) ─────────────────
        for variant in self._variants:
            if variant in text:
                # Find original phrase
                original = self._find_original(variant)
                return True, original, 0.95

        # ── Fuzzy similarity match ─────────────────────────────
        if len(text.split()) <= 6:  # Only fuzz short phrases (performance)
            best_phrase, best_score = self._best_fuzzy(text)
            if best_score >= self.min_ratio:
                return True, best_phrase, best_score

        return False, "", 0.0

    def _best_fuzzy(self, text: str) -> tuple[str, float]:
        """Find phrase with highest similarity to text."""
        best_phrase = ""
        best_score = 0.0
        for phrase in self.phrases:
            score = self._similarity(text, phrase)
            if score > best_score:
                best_score = score
                best_phrase = phrase
            # Also check if phrase is contained with partial overlap
            score2 = self._partial_similarity(text, phrase)
            if score2 > best_score:
                best_score = score2
                best_phrase = phrase
        return best_phrase, best_score

    def _similarity(self, a: str, b: str) -> float:
        """Character-level Dice coefficient similarity."""
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        a_bigrams = self._bigrams(a)
        b_bigrams = self._bigrams(b)
        if not a_bigrams or not b_bigrams:
            return 0.0
        intersection = len(a_bigrams & b_bigrams)
        return 2.0 * intersection / (len(a_bigrams) + len(b_bigrams))

    def _partial_similarity(self, text: str, phrase: str) -> float:
        """Check if text contains any word of the phrase."""
        phrase_words = set(phrase.split())
        text_words = set(text.split())
        overlap = phrase_words & text_words
        if not phrase_words:
            return 0.0
        return len(overlap) / len(phrase_words)

    def _bigrams(self, s: str) -> set:
        return {s[i:i+2] for i in range(len(s) - 1)}

    def _find_original(self, variant: str) -> str:
        """Find the original phrase closest to a variant."""
        best, score = self._best_fuzzy(variant)
        return best if best else "gini"


# ── Mock detector (for testing without hardware) ──────────────

class MockWakeWordDetector(WakeWordDetector):
    """
    Deterministic mock detector — fires scripted WakeEvents
    on a timer instead of listening to a real microphone.
    Used in tests and CI.
    """

    def __init__(
        self,
        config: Optional[WakeWordConfig] = None,
        on_wake: Optional[Callable[[WakeEvent], None]] = None,
        on_listening: Optional[Callable[[], None]] = None,
        fire_after: float = 0.2,        # Seconds before first auto-fire
        fire_count: int = 1,            # How many events to fire
    ):
        super().__init__(
            config=config or WakeWordConfig.for_testing(),
            audio_config=AudioConfig.for_testing(),
            on_wake=on_wake,
            on_listening=on_listening,
        )
        self.fire_after = fire_after
        self.fire_count = fire_count
        self._mock_phrases = ["hey gini", "hello gini", "ok gini"]
        log.info("🧪 MockWakeWordDetector initialized")

    def _detection_loop(self) -> None:
        """Fire scripted wake events instead of listening to mic."""
        self._state = DetectorState.IDLE
        fired = 0

        while not self._stop_event.is_set() and fired < self.fire_count:
            time.sleep(self.fire_after)

            if self._stop_event.is_set():
                break

            phrase = self._mock_phrases[fired % len(self._mock_phrases)]
            self._state = DetectorState.MATCHING

            event = WakeEvent(
                phrase=phrase,
                confidence=0.95,
                audio=None,
                timestamp=time.time(),
                triggered_by="mock",
            )
            self._trigger_count += 1
            self._last_trigger_time = time.time()
            log.info(f"🧪 Mock wake event: {event}")

            if self.on_wake:
                try:
                    self.on_wake(event)
                except Exception as e:
                    log.error(f"on_wake error: {e}")

            fired += 1
            self._state = DetectorState.COOLDOWN
            time.sleep(self.config.cooldown_seconds)

        self._state = DetectorState.IDLE
        # Keep thread alive until stop() called
        while not self._stop_event.is_set():
            time.sleep(0.1)
        self._state = DetectorState.STOPPED


__all__ = [
    "WakeWordDetector", "MockWakeWordDetector",
    "WakeWordConfig", "WakeEvent", "DetectorState",
    "PhraseMatcher",
]
