# ============================================================
# GINI-ORACLE-1 — TTS Engine Adapters
# voice/tts_engine.py
# ============================================================
"""
Speech synthesis adapters — all share the same interface:

    engine.synthesize(text) -> SynthesisResult

Adapters:
  Pyttsx3Engine  — offline, cross-platform, zero internet required
  GTTSEngine     — online, Google quality, good Hindi support
  EspeakEngine   — offline, system espeak binary
  MockTTSEngine  — testing, generates real WAV via numpy sine synthesis

Factory:
  create_tts_engine(config) -> best available engine
"""

import io
import os
import time
import wave
import struct
import math
import threading
from dataclasses import dataclass
from typing import Optional, List

from voice.tts_config import TTSConfig, TTSBackend, VoiceGender
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class VoiceInfo:
    """Metadata about a TTS voice."""
    id: str
    name: str
    language: str
    gender: str

    def __str__(self):
        return f"[{self.id}] {self.name} ({self.language}, {self.gender})"


@dataclass
class SynthesisResult:
    """Output of one TTS synthesis call."""
    success: bool
    audio_bytes: Optional[bytes]        # Raw WAV bytes (can be played or saved)
    duration_ms: float                  # How long synthesis took
    text: str                           # Input text
    backend: str                        # Which engine produced this
    error: Optional[str] = None

    @property
    def has_audio(self) -> bool:
        return self.audio_bytes is not None and len(self.audio_bytes) > 0

    def save(self, path: str) -> None:
        """Save audio to a WAV file."""
        if self.audio_bytes:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(self.audio_bytes)


# ── Pyttsx3 Engine ────────────────────────────────────────────

class Pyttsx3Engine:
    """
    Offline TTS using pyttsx3.
    Best choice for production — works completely without internet.
    Supports: Windows (SAPI5), macOS (NSSpeechSynthesizer), Linux (espeak/festival)

    Install: pip install pyttsx3
    """

    def __init__(self, config: TTSConfig):
        self.config = config
        self._engine = None
        self._lock = threading.Lock()   # pyttsx3 is not thread-safe
        self._loaded = False
        self._available_voices: List[VoiceInfo] = []

    def load(self) -> bool:
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            self._apply_settings()
            self._load_voices()
            self._select_voice()
            self._loaded = True
            log.info(
                f"✅ pyttsx3 loaded | "
                f"voices={len(self._available_voices)} | "
                f"rate={self.config.rate}"
            )
            return True
        except ImportError:
            log.warning("pyttsx3 not installed. Run: pip install pyttsx3")
            return False
        except Exception as e:
            log.error(f"pyttsx3 init failed: {e}")
            return False

    def _apply_settings(self):
        self._engine.setProperty("rate", self.config.rate)
        self._engine.setProperty("volume", self.config.volume)

    def _load_voices(self):
        voices = self._engine.getProperty("voices")
        self._available_voices = []
        for v in (voices or []):
            gender = "female" if "female" in v.name.lower() or "zira" in v.name.lower() else "male"
            lang = v.languages[0].decode() if v.languages else "en"
            self._available_voices.append(VoiceInfo(
                id=v.id, name=v.name, language=lang, gender=gender,
            ))

    def _select_voice(self):
        """Auto-select voice matching gender/name preference."""
        if self.config.voice_id:
            self._engine.setProperty("voice", self.config.voice_id)
            return

        if self.config.preferred_voice_name:
            for v in self._available_voices:
                if self.config.preferred_voice_name.lower() in v.name.lower():
                    self._engine.setProperty("voice", v.id)
                    log.info(f"Selected voice: {v}")
                    return

        # Match by gender
        target_gender = self.config.gender.value
        for v in self._available_voices:
            if target_gender in v.gender.lower():
                self._engine.setProperty("voice", v.id)
                log.info(f"Selected {target_gender} voice: {v}")
                return

    def list_voices(self) -> List[VoiceInfo]:
        return self._available_voices

    def set_rate(self, rate: int):
        if self._engine:
            self._engine.setProperty("rate", max(80, min(400, rate)))

    def set_volume(self, volume: float):
        if self._engine:
            self._engine.setProperty("volume", max(0.0, min(1.0, volume)))

    def synthesize(self, text: str) -> SynthesisResult:
        """Synthesize text to WAV bytes using pyttsx3."""
        if not self._loaded:
            return self._fail(text, "pyttsx3 not loaded")

        start = time.time()
        try:
            with self._lock:
                # pyttsx3 save_to_file → then read back as bytes
                tmp_path = f"/tmp/gini_tts_{int(time.time()*1000)}.wav"
                self._engine.save_to_file(text, tmp_path)
                self._engine.runAndWait()

                if not os.path.exists(tmp_path):
                    return self._fail(text, "Output file not created")

                with open(tmp_path, "rb") as f:
                    audio_bytes = f.read()
                os.remove(tmp_path)

            return SynthesisResult(
                success=True,
                audio_bytes=audio_bytes,
                duration_ms=(time.time() - start) * 1000,
                text=text,
                backend="pyttsx3",
            )
        except Exception as e:
            log.error(f"pyttsx3 synthesis error: {e}")
            return self._fail(text, str(e))

    def speak_direct(self, text: str) -> None:
        """Speak directly (blocking) — bypasses WAV step."""
        if not self._loaded:
            return
        with self._lock:
            self._engine.say(text)
            self._engine.runAndWait()

    def stop(self):
        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass

    def _fail(self, text: str, error: str) -> SynthesisResult:
        return SynthesisResult(
            success=False, audio_bytes=None,
            duration_ms=0, text=text, backend="pyttsx3", error=error,
        )


# ── gTTS Engine ───────────────────────────────────────────────

class GTTSEngine:
    """
    Google Text-to-Speech (online).
    High quality, supports Hindi natively.
    Requires internet connection.

    Install: pip install gtts
    """

    def __init__(self, config: TTSConfig):
        self.config = config
        self._loaded = False

    def load(self) -> bool:
        try:
            from gtts import gTTS
            self._loaded = True
            log.info("✅ gTTS loaded (online mode)")
            return True
        except ImportError:
            log.warning("gTTS not installed. Run: pip install gtts")
            return False

    def list_voices(self) -> List[VoiceInfo]:
        return [
            VoiceInfo("gtts-en", "Google English", "en", "neutral"),
            VoiceInfo("gtts-hi", "Google Hindi", "hi", "neutral"),
        ]

    def synthesize(self, text: str) -> SynthesisResult:
        if not self._loaded:
            return self._fail(text, "gTTS not loaded")

        start = time.time()
        try:
            from gtts import gTTS
            lang = "hi" if self.config.language.value == "hi" else "en"
            tts = gTTS(text=text, lang=lang, slow=False)

            buf = io.BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)
            mp3_bytes = buf.read()

            # gTTS returns MP3 — wrap in a marker for downstream handler
            return SynthesisResult(
                success=True,
                audio_bytes=mp3_bytes,
                duration_ms=(time.time() - start) * 1000,
                text=text,
                backend="gtts",
            )
        except Exception as e:
            log.error(f"gTTS synthesis error: {e}")
            return self._fail(text, str(e))

    def stop(self):
        pass  # gTTS is stateless

    def _fail(self, text: str, error: str) -> SynthesisResult:
        return SynthesisResult(
            success=False, audio_bytes=None,
            duration_ms=0, text=text, backend="gtts", error=error,
        )


# ── Espeak Engine ─────────────────────────────────────────────

class EspeakEngine:
    """
    Offline TTS using espeak/espeak-ng system binary.
    Ultra-lightweight. Install: sudo apt install espeak-ng
    """

    def __init__(self, config: TTSConfig):
        self.config = config
        self._binary = None
        self._loaded = False

    def load(self) -> bool:
        import subprocess
        for binary in ["espeak-ng", "espeak"]:
            result = subprocess.run(["which", binary], capture_output=True)
            if result.returncode == 0:
                self._binary = binary
                self._loaded = True
                log.info(f"✅ espeak loaded: {binary}")
                return True
        log.warning("espeak/espeak-ng not found. Install: sudo apt install espeak-ng")
        return False

    def list_voices(self) -> List[VoiceInfo]:
        return [
            VoiceInfo("en", "espeak English", "en", "neutral"),
            VoiceInfo("hi", "espeak Hindi", "hi", "neutral"),
        ]

    def synthesize(self, text: str) -> SynthesisResult:
        if not self._loaded:
            return self._fail(text, "espeak not available")

        import subprocess
        start = time.time()
        tmp_path = f"/tmp/gini_espeak_{int(time.time()*1000)}.wav"
        try:
            lang = "hi" if self.config.language.value == "hi" else "en"
            speed = max(80, min(390, self.config.rate))
            cmd = [
                self._binary,
                "-v", lang,
                "-s", str(speed),
                "-w", tmp_path,
                text,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=10)
            if result.returncode != 0:
                return self._fail(text, result.stderr.decode())

            with open(tmp_path, "rb") as f:
                audio_bytes = f.read()
            os.remove(tmp_path)

            return SynthesisResult(
                success=True,
                audio_bytes=audio_bytes,
                duration_ms=(time.time() - start) * 1000,
                text=text,
                backend="espeak",
            )
        except Exception as e:
            log.error(f"espeak error: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return self._fail(text, str(e))

    def stop(self):
        import subprocess
        try:
            subprocess.run(["pkill", self._binary], capture_output=True)
        except Exception:
            pass

    def _fail(self, text: str, error: str) -> SynthesisResult:
        return SynthesisResult(
            success=False, audio_bytes=None,
            duration_ms=0, text=text, backend="espeak", error=error,
        )


# ── Mock TTS Engine ───────────────────────────────────────────

class MockTTSEngine:
    """
    Deterministic mock TTS for testing.
    Generates REAL playable WAV audio using numpy sine wave synthesis.
    Pitch and duration vary per character — simulates natural speech.
    No external dependencies beyond numpy.
    """

    # Phoneme frequency map — different chars → different pitches
    _CHAR_FREQS = {
        'a': 220, 'e': 260, 'i': 310, 'o': 240, 'u': 200,
        's': 400, 't': 380, 'n': 280, 'r': 300, 'l': 270,
        ' ': 0,   ',': 0,   '.': 0,
    }
    _DEFAULT_FREQ = 250

    def __init__(self, config: TTSConfig):
        self.config = config
        self._loaded = True
        self._voices = [
            VoiceInfo("mock-female", "Mock Female Voice", "en", "female"),
            VoiceInfo("mock-male", "Mock Male Voice", "en", "male"),
            VoiceInfo("mock-hindi", "Mock Hindi Voice", "hi", "neutral"),
        ]
        log.info("🧪 MockTTSEngine initialized")

    def load(self) -> bool:
        return True

    def list_voices(self) -> List[VoiceInfo]:
        return self._voices

    def synthesize(self, text: str) -> SynthesisResult:
        """Generate a real WAV file from text using stdlib sine synthesis."""
        start = time.time()
        try:
            sample_rate = 22050
            rate_factor = 175 / max(self.config.rate, 50)
            duration = max(0.3, len(text) * 0.08 * rate_factor)

            letters = [c for c in text if c.isalpha()]
            base_freq = sum(
                self._CHAR_FREQS.get(c.lower(), self._DEFAULT_FREQ)
                for c in letters
            ) / max(1, len(letters))
            base_freq = max(150, min(500, base_freq))

            n_samples = int(sample_rate * duration)
            attack = max(1, int(0.05 * n_samples))
            decay = max(1, int(0.1 * n_samples))
            samples = []

            for i in range(n_samples):
                t = i / sample_rate
                signal = (
                    0.5 * math.sin(2 * math.pi * base_freq * t) +
                    0.25 * math.sin(2 * math.pi * base_freq * 2 * t) +
                    0.12 * math.sin(2 * math.pi * base_freq * 3 * t) +
                    0.06 * math.sin(2 * math.pi * base_freq * 4 * t)
                )
                if i < attack:
                    envelope = i / attack
                elif i > n_samples - decay:
                    envelope = max(0.0, (n_samples - i) / decay)
                else:
                    envelope = 1.0
                value = int(max(-1.0, min(1.0, signal * envelope * self.config.volume)) * 32767)
                samples.append(struct.pack("<h", value))

            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                wf.writeframes(b"".join(samples))
            audio_bytes = buf.getvalue()

            return SynthesisResult(
                success=True,
                audio_bytes=audio_bytes,
                duration_ms=(time.time() - start) * 1000,
                text=text,
                backend="mock",
            )
        except Exception as e:
            log.error(f"MockTTS synthesis error: {e}")
            return SynthesisResult(
                success=False, audio_bytes=None,
                duration_ms=0, text=text, backend="mock", error=str(e),
            )

    def stop(self):
        pass


# ── Factory ───────────────────────────────────────────────────

def create_tts_engine(config: TTSConfig):
    """
    Factory: return best available TTS engine.
    Priority: pyttsx3 → espeak → gTTS → Mock
    """
    if config.backend == TTSBackend.MOCK:
        return MockTTSEngine(config)

    if config.backend == TTSBackend.PYTTSX3:
        e = Pyttsx3Engine(config)
        if e.load():
            return e
        log.warning("pyttsx3 unavailable — trying espeak")

    if config.backend in (TTSBackend.PYTTSX3, TTSBackend.ESPEAK):
        e = EspeakEngine(config)
        if e.load():
            return e
        log.warning("espeak unavailable — trying gTTS")

    if config.backend == TTSBackend.GTTS:
        e = GTTSEngine(config)
        if e.load():
            return e

    log.warning("⚠️ All TTS engines unavailable — using mock")
    return MockTTSEngine(config)


__all__ = [
    "VoiceInfo", "SynthesisResult",
    "Pyttsx3Engine", "GTTSEngine", "EspeakEngine", "MockTTSEngine",
    "create_tts_engine",
]
