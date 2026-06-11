# ============================================================
# GINI-ORACLE-1 — Speech Recognizer
# voice/speech_recognizer.py
# ============================================================
"""
Speech-to-text recognition layer.
Implements an adapter pattern so backends are swappable:

  WhisperRecognizer  — offline, high accuracy, Hindi-accent support
  VoskRecognizer     — offline, lightweight, fast
  MockRecognizer     — deterministic, for testing

All adapters implement the same interface:
  recognize(audio: CapturedAudio) -> RecognitionResult

Usage:
    recognizer = create_recognizer(config)
    result = recognizer.recognize(audio)
    if result.success:
        print(result.text)
"""

import time
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

from voice.audio_capture import CapturedAudio
from voice.audio_config import AudioConfig, AudioBackend, Language
from utils.logger import get_logger

log = get_logger(__name__)


class RecognitionStatus(str, Enum):
    SUCCESS      = "success"
    EMPTY        = "empty"           # Audio captured but no speech found
    LOW_CONF     = "low_confidence"  # Recognized but below confidence threshold
    ENGINE_ERROR = "engine_error"    # STT engine failure
    TIMEOUT      = "timeout"


@dataclass
class RecognitionResult:
    """Result of a speech recognition attempt."""
    text: str                               # Recognized text (empty if failed)
    confidence: float                       # 0.0 – 1.0
    status: RecognitionStatus
    language_detected: str = "en"
    duration_ms: float = 0.0               # Time taken by recognition
    alternatives: List[str] = field(default_factory=list)  # Alternative transcripts
    raw_output: Optional[dict] = None       # Raw engine output for debugging

    @property
    def success(self) -> bool:
        return self.status == RecognitionStatus.SUCCESS and bool(self.text)

    @property
    def normalized_text(self) -> str:
        """Lowercase, stripped text ready for intent detection."""
        return self.text.lower().strip()

    def __str__(self):
        return (
            f"RecognitionResult('{self.text}' | "
            f"conf={self.confidence:.2f} | {self.status.value})"
        )


# ── Whisper Adapter ───────────────────────────────────────────

class WhisperRecognizer:
    """
    Offline speech recognition using OpenAI Whisper (local).
    Excellent Hindi-accent English and basic Hindi support.

    Install: pip install openai-whisper
    Models:  tiny (39M) | base (74M) | small (244M) | medium (769M) | large (1.5G)

    Recommended for Gini: 'base' model (~74MB, fast, accurate)
    """

    def __init__(self, config: AudioConfig):
        self.config = config
        self._model = None
        self._model_name = config.whisper_model
        self._loaded = False

    def load(self) -> bool:
        """Load the Whisper model. Call once at startup."""
        try:
            import whisper
            log.info(f"⏳ Loading Whisper model '{self._model_name}'...")
            self._model = whisper.load_model(self._model_name)
            self._loaded = True
            log.info(f"✅ Whisper '{self._model_name}' loaded")
            return True
        except ImportError:
            log.warning("Whisper not installed. Run: pip install openai-whisper")
            return False
        except Exception as e:
            log.error(f"Whisper load failed: {e}")
            return False

    def recognize(self, audio: CapturedAudio) -> RecognitionResult:
        """Run Whisper STT on captured audio."""
        if not self._loaded or not self._model:
            return RecognitionResult(
                text="", confidence=0.0,
                status=RecognitionStatus.ENGINE_ERROR,
                raw_output={"error": "Model not loaded"},
            )

        import io, tempfile, os
        start = time.time()
        try:
            # Whisper expects a WAV file or numpy array
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio.to_wav_bytes())
                tmp_path = tmp.name

            # Language hint for Hindi-accent English
            lang = None  # Let Whisper auto-detect — better for mixed languages
            if self.config.language == Language.HINDI:
                lang = "hi"
            elif self.config.language == Language.HINDI_ENGLISH:
                lang = None  # auto-detect handles Hinglish best

            result = self._model.transcribe(
                tmp_path,
                language=lang,
                task="transcribe",
                fp16=False,
                verbose=False,
            )
            os.unlink(tmp_path)

            text = result.get("text", "").strip()
            segments = result.get("segments", [])
            avg_conf = (
                sum(s.get("avg_logprob", -1) for s in segments) / len(segments)
                if segments else -1.0
            )
            # Convert log prob to 0–1 confidence (approx)
            confidence = max(0.0, min(1.0, (avg_conf + 1.0)))

            if not text:
                return RecognitionResult(
                    text="", confidence=0.0,
                    status=RecognitionStatus.EMPTY,
                    duration_ms=(time.time() - start) * 1000,
                )

            return RecognitionResult(
                text=text,
                confidence=confidence,
                status=RecognitionStatus.SUCCESS,
                language_detected=result.get("language", "en"),
                duration_ms=(time.time() - start) * 1000,
                raw_output={"segments": len(segments)},
            )

        except Exception as e:
            log.error(f"Whisper recognition error: {e}")
            return RecognitionResult(
                text="", confidence=0.0,
                status=RecognitionStatus.ENGINE_ERROR,
                raw_output={"error": str(e)},
            )


# ── Vosk Adapter ──────────────────────────────────────────────

class VoskRecognizer:
    """
    Offline speech recognition using Vosk.
    Lightweight, fast, runs on low-end hardware.
    Supports English and Hindi models.

    Install: pip install vosk
    Models:  Download from https://alphacephei.com/vosk/models
             vosk-model-en-us-0.22 (English)
             vosk-model-hi-0.22    (Hindi)
    """

    def __init__(self, config: AudioConfig, model_path: str = "models/vosk-en"):
        self.config = config
        self.model_path = model_path
        self._recognizer = None
        self._model = None
        self._loaded = False

    def load(self) -> bool:
        try:
            from vosk import Model, KaldiRecognizer
            import os
            candidates = [
                self.model_path,
                "models/vosk-en",
                "models/vosk-model-en-us-0.22",
                "models/vosk-model-hi-0.22",
                "models/vosk",
            ]
            self.model_path = next((p for p in candidates if os.path.exists(p)), self.model_path)
            if not os.path.exists(self.model_path):
                log.warning(
                    f"Vosk model not found at '{self.model_path}'. "
                    f"Download from: https://alphacephei.com/vosk/models"
                )
                return False
            self._model = Model(self.model_path)
            self._recognizer = KaldiRecognizer(self._model, self.config.sample_rate)
            self._recognizer.SetWords(True)
            self._loaded = True
            log.info(f"✅ Vosk model loaded from '{self.model_path}'")
            return True
        except ImportError:
            log.warning("Vosk not installed. Run: pip install vosk")
            return False
        except Exception as e:
            log.error(f"Vosk load failed: {e}")
            return False

    def recognize(self, audio: CapturedAudio) -> RecognitionResult:
        if not self._loaded or not self._recognizer:
            return RecognitionResult(
                text="", confidence=0.0,
                status=RecognitionStatus.ENGINE_ERROR,
                raw_output={"error": "Vosk model not loaded"},
            )

        import json
        start = time.time()
        try:
            # Feed chunks to Vosk
            chunk_size = self.config.chunk_size * self.config.sample_width
            frames = audio.frames

            for i in range(0, len(frames), chunk_size):
                self._recognizer.AcceptWaveform(frames[i:i + chunk_size])

            raw = json.loads(self._recognizer.FinalResult())
            text = raw.get("text", "").strip()

            if not text:
                return RecognitionResult(
                    text="", confidence=0.0,
                    status=RecognitionStatus.EMPTY,
                    duration_ms=(time.time() - start) * 1000,
                )

            # Vosk word-level confidence
            words = raw.get("result", [])
            avg_conf = (
                sum(w.get("conf", 0.5) for w in words) / len(words)
                if words else 0.5
            )

            return RecognitionResult(
                text=text,
                confidence=avg_conf,
                status=RecognitionStatus.SUCCESS,
                duration_ms=(time.time() - start) * 1000,
                raw_output=raw,
            )
        except Exception as e:
            log.error(f"Vosk recognition error: {e}")
            return RecognitionResult(
                text="", confidence=0.0,
                status=RecognitionStatus.ENGINE_ERROR,
                raw_output={"error": str(e)},
            )


# ── Mock Recognizer ───────────────────────────────────────────

class MockRecognizer:
    """
    Deterministic mock recognizer for testing.
    Returns scripted responses in sequence.
    Simulates realistic confidence scores and timing.
    """

    # Predefined responses cycling through common Gini commands
    _DEFAULT_RESPONSES = [
        ("open spotify",                     0.97),
        ("set volume to 50",                 0.94),
        ("play next song",                   0.96),
        ("search for weather in lucknow",    0.92),
        ("set a timer for 10 minutes",       0.95),
        ("what is machine learning",         0.93),
        ("remember I prefer dark mode",      0.91),
        ("turn off the lights in bedroom",   0.88),
        ("gini band karo music",             0.85),   # Hindi command
        ("call mom",                         0.97),
    ]

    def __init__(self, config: AudioConfig, responses=None):
        self.config = config
        self._responses = responses or self._DEFAULT_RESPONSES
        self._idx = 0
        self._loaded = True
        log.info("🧪 MockRecognizer initialized")

    def load(self) -> bool:
        return True

    def recognize(self, audio: CapturedAudio) -> RecognitionResult:
        """Return next scripted response."""
        time.sleep(0.05)  # Simulate processing time
        text, confidence = self._responses[self._idx % len(self._responses)]
        self._idx += 1
        log.debug(f"MockRecognizer → '{text}' ({confidence:.2f})")
        return RecognitionResult(
            text=text,
            confidence=confidence,
            status=RecognitionStatus.SUCCESS,
            language_detected="en",
            duration_ms=50.0,
            alternatives=[],
        )


# ── Factory ───────────────────────────────────────────────────

def create_recognizer(config: AudioConfig):
    """
    Factory: create the best available recognizer.
    Priority: Whisper → Vosk. Does not automatically fall back to mock.
    """
    if config.backend == AudioBackend.MOCK:
        return MockRecognizer(config)

    if config.backend == AudioBackend.WHISPER:
        whisper_recognizer = WhisperRecognizer(config)
        if whisper_recognizer.load():
            return whisper_recognizer
        log.warning("Whisper unavailable, trying Vosk...")

        if config.fallback_backend == AudioBackend.VOSK:
            vosk_recognizer = VoskRecognizer(config)
            if vosk_recognizer.load():
                return vosk_recognizer
            log.warning("Vosk unavailable")

    elif config.backend == AudioBackend.VOSK:
        vosk_recognizer = VoskRecognizer(config)
        if vosk_recognizer.load():
            return vosk_recognizer
        log.warning("Vosk unavailable")

    raise RuntimeError(
        "No offline speech recognizer available. Install Whisper or Vosk and download the required model files."
    )


__all__ = [
    "RecognitionResult", "RecognitionStatus",
    "WhisperRecognizer", "VoskRecognizer", "MockRecognizer",
    "create_recognizer",
]
