# ============================================================
# GINI-ORACLE-1 — Voice Engine (Full Implementation)
# voice/voice_engine.py
# ============================================================
"""
VoiceEngine is the unified voice pipeline for Gini.ai.
Orchestrates the full speech-to-text flow:

  Microphone
    → AudioCapture     (device selection, mic capture, silence detection)
    → AudioPreprocessor (noise reduction, normalization, high-pass filter)
    → SpeechRecognizer  (Whisper / Vosk / Mock)
    → HindiNormalizer   (Hinglish / accent normalization)
    → VoiceResult       (clean text ready for intent detection)

Features:
  ✅ Offline-first (Whisper or Vosk — no internet needed)
  ✅ English + Hindi-accent English + basic Hindi commands
  ✅ Noise tolerance via spectral subtraction
  ✅ Silence detection (auto phrase-end detection)
  ✅ Timeout handling (listen + phrase timeouts)
  ✅ Microphone error handling
  ✅ Retry with backoff
  ✅ Device selection (auto or manual)
  ✅ Streaming support (for future GUI integration)
"""

import time
import asyncio
from dataclasses import dataclass
from typing import Optional, AsyncGenerator, Callable

from voice.audio_config import AudioConfig, AudioBackend, Language
from voice.audio_capture import create_capture_backend, CapturedAudio, CaptureState
from voice.audio_preprocessor import AudioPreprocessor
from voice.speech_recognizer import (
    create_recognizer, RecognitionResult, RecognitionStatus,
)
from voice.hindi_normalizer import HindiNormalizer
from voice.tts_config import TTSConfig, TTSBackend
from voice.wake_word_detector import (
    WakeWordDetector, MockWakeWordDetector,
    WakeWordConfig, WakeEvent, DetectorState,
)
from voice.voice_output_manager import VoiceOutputManager, SpeechPriority, OutputState
from config.settings import settings
from utils.logger import get_logger
from core.voice_resilience import get_voice_resilience

log = get_logger(__name__)


@dataclass
class VoiceResult:
    """Final output of the full voice pipeline."""
    text: str                          # Clean, normalized text
    original_text: str                 # Raw STT output before normalization
    confidence: float                  # Recognition confidence
    success: bool
    language_detected: str
    had_wake_word: bool
    was_translated: bool               # Hindi → English translation happened
    duration_ms: float                 # Total pipeline time
    error: Optional[str] = None

    @property
    def normalized(self) -> str:
        return self.text.lower().strip()

    def __str__(self):
        return (
            f"VoiceResult('{self.text}' | "
            f"conf={self.confidence:.2f} | "
            f"lang={self.language_detected} | "
            f"{'✅' if self.success else '❌'})"
        )


class VoiceEngine:
    """
    Unified offline-first voice-to-text pipeline.
    Wires together: capture → preprocess → recognize → normalize.
    """

    def __init__(self, config: Optional[AudioConfig] = None):
        self.config = config or self._default_config()
        self.enabled = settings.voice_enabled
        self.language = settings.voice_language

        # Pipeline components
        self._capture = None
        self._preprocessor = AudioPreprocessor(self.config)
        self._recognizer = None
        self._normalizer = HindiNormalizer()
        self._device_index: Optional[int] = None

        # State
        self._initialized = False
        self._listening = False
        self._last_recovery: Optional[dict] = None

        # TTS output manager
        self._output_manager: Optional[VoiceOutputManager] = None

        # Wake word detector
        self._wake_detector: Optional[WakeWordDetector] = None

        log.info(
            f"🎙️ VoiceEngine created | "
            f"backend={self.config.backend.value} | "
            f"lang={self.config.language.value}"
        )

    def _default_config(self) -> AudioConfig:
        """Build config from global settings."""
        try:
            language = Language(settings.voice_language)
        except ValueError:
            language = Language.HINDI_ENGLISH
        return AudioConfig(
            backend=AudioBackend.WHISPER,
            language=language,
        )

    # ── Initialization ────────────────────────────────────────

    def initialize(self) -> bool:
        """
        Initialize all pipeline components.
        Call once at startup (handled by bootstrap/lifecycle).
        Returns True if ready to listen.
        """
        if self._initialized:
            return True

        log.info("⚙️ Initializing VoiceEngine pipeline...")

        # ── Capture backend ───────────────────────────────────
        self._capture = create_capture_backend(self.config)
        if not self._capture.initialize():
            log.error("Audio capture backend failed to initialize")
            recovery = get_voice_resilience()
            recovery.mic_available = False
            self.enabled = False
            self._last_recovery = {
                "fallback_mode": "text_input",
                "message": "Microphone unavailable. Text input mode is active.",
                "can_retry": True,
            }
            return False

        # ── Device selection ──────────────────────────────────
        self._device_index = self._capture.select_device()
        devices = self._capture.list_devices()
        get_voice_resilience().mic_available = bool(devices)
        log.info(f"  🎤 Available devices: {len(devices)}")
        for d in devices:
            log.info(f"     {d}")

        # ── Noise calibration ─────────────────────────────────
        self._capture.calibrate_noise(self._device_index)

        # ── Speech recognizer ─────────────────────────────────
        self._recognizer = create_recognizer(self.config)

        self._initialized = True
        log.info("✅ VoiceEngine pipeline ready")
        return True

    # ── Main listen API ───────────────────────────────────────

    def listen(self) -> VoiceResult:
        """
        Synchronous: capture + recognize one phrase.
        Blocks until speech detected + phrase complete (or timeout/error).

        Returns a VoiceResult — never raises.
        """
        if not self._initialized:
            self.initialize()

        if not self._initialized:
            return self._failed_result(
                error="mic_failure",
                error_msg="Microphone unavailable. Text input mode is active.",
                elapsed=0,
            )

        return self._run_pipeline_sync()

    async def listen_async(self) -> VoiceResult:
        """
        Async wrapper around listen().
        Use from FastAPI endpoints or async contexts.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.listen)

    def listen_with_retry(self, max_retries: Optional[int] = None) -> VoiceResult:
        """
        Listen with automatic retry on failure.
        Retries on: engine error, empty result, low confidence.
        Does NOT retry on: timeout (user chose to be silent).
        """
        if not self._initialized:
            self.initialize()

        retries = max_retries or self.config.max_retries
        last_result = None

        for attempt in range(retries + 1):
            if attempt > 0:
                log.info(f"🔄 Retry {attempt}/{retries}...")
                time.sleep(self.config.retry_delay)

            result = self._run_pipeline_sync()
            last_result = result

            if result.success:
                return result

            # Don't retry timeouts — user intentionally silent
            if result.error and "timeout" in result.error.lower():
                log.info("Timeout — not retrying")
                return result

            log.warning(f"Attempt {attempt + 1} failed: {result.error or 'empty'}")

        log.warning(f"All {retries + 1} attempts failed")
        return last_result

    async def stream_listen(
        self, on_chunk: Optional[Callable] = None
    ) -> AsyncGenerator[VoiceResult, None]:
        """
        Async generator: continuously listen and yield VoiceResults.
        For use with streaming GUI or websocket endpoints.
        Stops when self._listening = False.

        Usage:
            engine.start_streaming()
            async for result in engine.stream_listen():
                print(result.text)
            engine.stop_streaming()
        """
        self._listening = True
        if not self._initialized:
            self.initialize()

        log.info("🔴 Streaming voice input started")
        while self._listening:
            result = await self.listen_async()
            if result.success:
                yield result
            await asyncio.sleep(0.05)  # Small gap between phrases

        log.info("⏹️ Streaming voice input stopped")

    def start_streaming(self):
        self._listening = True

    def stop_streaming(self):
        self._listening = False

    # ── Core Pipeline ─────────────────────────────────────────

    def _run_pipeline_sync(self) -> VoiceResult:
        """
        The actual capture → preprocess → recognize → normalize pipeline.
        Always returns a VoiceResult — exception-safe.
        """
        start = time.time()

        try:
            # ── Step 1: Capture ───────────────────────────────
            log.info("🎤 Capturing audio...")
            audio: Optional[CapturedAudio] = self._capture.capture(self._device_index)

            if audio is None:
                return self._failed_result(
                    error="timeout",
                    error_msg="No speech detected within timeout period",
                    elapsed=time.time() - start,
                )

            # ── Step 2: Preprocess ────────────────────────────
            log.debug("🔧 Preprocessing audio...")
            audio = self._preprocessor.process(audio)
            stats = self._preprocessor.get_audio_stats(audio)
            log.debug(f"Audio stats: {stats}")

            # ── Step 3: Recognize ─────────────────────────────
            log.info("🧠 Running speech recognition...")
            rec_result: RecognitionResult = self._recognizer.recognize(audio)

            if not rec_result.success:
                return self._failed_result(
                    error=rec_result.status.value,
                    error_msg=f"Recognition failed: {rec_result.status.value}",
                    elapsed=time.time() - start,
                )

            # ── Step 4: Hindi normalization ───────────────────
            norm = self._normalizer.process(rec_result.text)

            # ── Step 5: Check if only wake word ───────────────
            if self._normalizer.is_wake_word_only(rec_result.text):
                log.info("Wake word only — prompting for command")
                return VoiceResult(
                    text="",
                    original_text=rec_result.text,
                    confidence=rec_result.confidence,
                    success=False,
                    language_detected=rec_result.language_detected,
                    had_wake_word=True,
                    was_translated=False,
                    duration_ms=(time.time() - start) * 1000,
                    error="wake_word_only",
                )

            elapsed = (time.time() - start) * 1000
            log.info(
                f"✅ Recognized: '{norm['final']}' "
                f"(conf={rec_result.confidence:.2f}, {elapsed:.0f}ms)"
            )

            return VoiceResult(
                text=norm["final"],
                original_text=rec_result.text,
                confidence=rec_result.confidence,
                success=True,
                language_detected=rec_result.language_detected,
                had_wake_word=norm["had_wake_word"],
                was_translated=norm["was_translated"],
                duration_ms=elapsed,
            )

        except Exception as e:
            log.error(f"VoiceEngine pipeline error: {e}", exc_info=True)
            return self._failed_result(
                error="pipeline_error",
                error_msg=str(e),
                elapsed=time.time() - start,
            )

    # ── TTS output ────────────────────────────────────────────

    def _ensure_output_manager(self) -> VoiceOutputManager:
        """Lazy-init VoiceOutputManager on first speak() call."""
        if self._output_manager is None:
            tts_cfg = TTSConfig(
                backend=TTSBackend.MOCK
                if self.config.backend == AudioBackend.MOCK
                else TTSBackend.PYTTSX3,
                rate=175,
                volume=1.0,
            )
            self._output_manager = VoiceOutputManager(config=tts_cfg)
            self._output_manager.start()
            log.info(f"🔊 VoiceOutputManager started | backend={tts_cfg.backend.value}")
        return self._output_manager

    def speak(self, text: str, priority: SpeechPriority = SpeechPriority.NORMAL) -> None:
        """
        Queue text for speech output. Non-blocking.
        Long text is automatically chunked and played sequentially.
        """
        if not text or not text.strip():
            return
        try:
            manager = self._ensure_output_manager()
            manager.speak(text, priority=priority)
            log.info(f"🔊 Queued speech: '{text[:60]}{'...' if len(text) > 60 else ''}'")
        except Exception as e:
            log.error(f"TTS queue failed: {e}", exc_info=True)
            recovery = get_voice_resilience()
            recovery.tts_enabled = False
            self._last_recovery = {
                "fallback_mode": "text_only",
                "message": "Voice output temporarily disabled. Using text only.",
                "can_retry": True,
            }

    def speak_priority(self, text: str) -> None:
        """Interrupt current speech and speak immediately."""
        manager = self._ensure_output_manager()
        manager.speak_priority(text)

    def stop_speaking(self) -> None:
        """Stop current speech and clear queue."""
        if self._output_manager:
            self._output_manager.stop()

    def set_speech_rate(self, rate: int) -> None:
        """Set speech rate in words per minute (80–400)."""
        manager = self._ensure_output_manager()
        manager.set_rate(rate)

    def set_speech_volume(self, volume: float) -> None:
        """Set volume (0.0–1.0)."""
        manager = self._ensure_output_manager()
        manager.set_volume(volume)

    def set_voice(self, voice_id: str) -> None:
        """Switch TTS voice by ID."""
        manager = self._ensure_output_manager()
        manager.set_voice(voice_id)

    def list_voices(self) -> list:
        """List available TTS voices."""
        manager = self._ensure_output_manager()
        return manager.list_voices()

    @property
    def is_speaking(self) -> bool:
        """True if currently outputting speech."""
        return self._output_manager is not None and self._output_manager.is_speaking

    def tts_status(self) -> dict:
        """Return TTS subsystem status."""
        if self._output_manager:
            return self._output_manager.status()
        return {"state": "not_initialized"}

    # ── Device management ─────────────────────────────────────

    def list_devices(self) -> list:
        """Return list of available audio input devices."""
        if not self._initialized:
            self.initialize()
        return self._capture.list_devices()

    def set_device(self, device_index: int) -> None:
        """Manually select a microphone device."""
        self._device_index = device_index
        log.info(f"Microphone device set to index: {device_index}")

    # ── Helpers ───────────────────────────────────────────────

    def _failed_result(self, error: str, error_msg: str, elapsed: float) -> VoiceResult:
        return VoiceResult(
            text="",
            original_text="",
            confidence=0.0,
            success=False,
            language_detected="unknown",
            had_wake_word=False,
            was_translated=False,
            duration_ms=elapsed * 1000,
            error=error_msg,
        )

    # ── Wake word detection ──────────────────────────────────

    def start_wake_detection(
        self,
        on_wake=None,
        on_listening=None,
        wake_config: Optional[WakeWordConfig] = None,
        mock: bool = False,
    ) -> None:
        """
        Start always-listening wake word detection.
        Non-blocking — runs in a daemon background thread.

        Args:
            on_wake:      Callable(WakeEvent) — fired on wake detection
            on_listening: Callable() — fired when mic picks up speech energy
            wake_config:  Custom WakeWordConfig (uses defaults if None)
            mock:         Use MockWakeWordDetector (no real mic needed)
        """
        if self._wake_detector and self._wake_detector.is_running():
            log.warning("Wake detection already running")
            return

        cfg = wake_config or WakeWordConfig(
            energy_threshold=self.config.energy_threshold,
        )

        if mock or self.config.backend == AudioBackend.MOCK:
            self._wake_detector = MockWakeWordDetector(
                config=cfg,
                on_wake=on_wake,
                on_listening=on_listening,
            )
        else:
            self._wake_detector = WakeWordDetector(
                config=cfg,
                audio_config=self.config,
                on_wake=on_wake,
                on_listening=on_listening,
            )

        self._wake_detector.start()
        log.info("👂 Wake word detection activated")

    def stop_wake_detection(self) -> None:
        """Stop wake word detection."""
        if self._wake_detector:
            self._wake_detector.stop()
            log.info("⏹ Wake word detection stopped")

    def add_wake_phrase(self, phrase: str) -> None:
        """Add a custom wake phrase at runtime."""
        if self._wake_detector:
            self._wake_detector.add_phrase(phrase)

    def wake_status(self) -> dict:
        """Return wake detector status."""
        if self._wake_detector:
            return self._wake_detector.status()
        return {"state": "not_initialized"}

    def terminate(self):
        """Cleanup resources on shutdown."""
        self._listening = False
        if self._capture:
            self._capture.terminate()
        if self._output_manager:
            self._output_manager.stop_worker()
        if self._wake_detector:
            self._wake_detector.stop()
        log.info("VoiceEngine terminated")

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def backend(self) -> str:
        return self.config.backend.value

    def status(self) -> dict:
        return {
            "initialized": self._initialized,
            "enabled":     self.enabled,
            "backend":     self.config.backend.value,
            "language":    self.config.language.value,
            "device_index":self._device_index,
            "tts":         self.tts_status(),
            "is_speaking": self.is_speaking,
            "wake":        self.wake_status(),
            "last_recovery": self._last_recovery,
        }


__all__ = ["VoiceEngine", "VoiceResult", "WakeWordConfig", "WakeEvent"]
