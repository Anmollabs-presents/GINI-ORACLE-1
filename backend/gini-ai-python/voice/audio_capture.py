# ============================================================
# GINI-ORACLE-1 — Audio Capture Module
# voice/audio_capture.py
# ============================================================
"""
Handles all microphone interaction:
  - Device discovery and selection
  - Raw audio capture (chunk-based streaming)
  - Silence detection using RMS energy
  - Ambient noise calibration
  - Timeout and error handling
  - Thread-safe audio queue

Designed for offline-first use. Works with PyAudio when available,
falls back to a robust mock for CI/testing environments.
"""

import io
import wave
import time
import struct
import threading
import queue
import math
from dataclasses import dataclass
from typing import Optional, List, Generator
from enum import Enum

from voice.audio_config import AudioConfig, AudioBackend
from utils.logger import get_logger

log = get_logger(__name__)


class CaptureState(str, Enum):
    IDLE        = "idle"
    CALIBRATING = "calibrating"
    LISTENING   = "listening"
    CAPTURING   = "capturing"
    TIMEOUT     = "timeout"
    ERROR       = "error"


@dataclass
class AudioDevice:
    """Represents a discovered microphone device."""
    index: int
    name: str
    channels: int
    sample_rate: float
    is_default: bool = False

    def __str__(self):
        default = " [DEFAULT]" if self.is_default else ""
        return f"[{self.index}] {self.name}{default}"


@dataclass
class AudioChunk:
    """A captured audio chunk with metadata."""
    data: bytes
    rms_energy: float
    timestamp: float
    is_speech: bool


@dataclass
class CapturedAudio:
    """A complete captured audio segment, ready for recognition."""
    frames: bytes                  # Raw PCM bytes
    sample_rate: int
    channels: int
    sample_width: int
    duration_seconds: float
    peak_energy: float
    language_hint: str = "en"

    def to_wav_bytes(self) -> bytes:
        """Export as WAV file bytes — compatible with Whisper/Vosk."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(self.frames)
        return buf.getvalue()

    def to_wav_file(self, path: str) -> None:
        """Save as WAV file to disk."""
        with open(path, "wb") as f:
            f.write(self.to_wav_bytes())


def _compute_rms(data: bytes, sample_width: int = 2) -> float:
    """Compute RMS energy from raw PCM bytes. Fast and dependency-free."""
    if not data:
        return 0.0
    try:
        fmt = f"{len(data) // sample_width}h"
        samples = struct.unpack(fmt, data[:len(data) - len(data) % sample_width])
        if not samples:
            return 0.0
        mean_sq = sum(s * s for s in samples) / len(samples)
        return math.sqrt(mean_sq)
    except Exception:
        return 0.0


# ── PyAudio backend ───────────────────────────────────────────

class PyAudioCapture:
    """
    Real microphone capture using PyAudio.
    Activated when PyAudio + PortAudio are available.
    """

    def __init__(self, config: AudioConfig):
        self.config = config
        self._pa = None
        self._stream = None
        self._energy_threshold = config.energy_threshold
        self._state = CaptureState.IDLE

    def initialize(self) -> bool:
        try:
            import pyaudio
            self._pa = pyaudio.PyAudio()
            log.info("🎤 PyAudio backend initialized")
            return True
        except Exception as e:
            log.error(f"PyAudio init failed: {e}")
            return False

    def list_devices(self) -> List[AudioDevice]:
        """List all available input devices."""
        if not self._pa:
            return []
        import pyaudio
        devices = []
        default_idx = self._pa.get_default_input_device_info().get("index", 0)
        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                devices.append(AudioDevice(
                    index=i,
                    name=info["name"],
                    channels=info["maxInputChannels"],
                    sample_rate=info["defaultSampleRate"],
                    is_default=(i == default_idx),
                ))
        return devices

    def select_device(self) -> Optional[int]:
        """Auto-select best microphone based on config preferences."""
        devices = self.list_devices()
        if not devices:
            return None

        # Try preferred device name first
        if self.config.preferred_device_name:
            for d in devices:
                if self.config.preferred_device_name.lower() in d.name.lower():
                    log.info(f"Using preferred device: {d}")
                    return d.index

        # Use config device index if specified
        if self.config.device_index is not None:
            return self.config.device_index

        # Fall back to default
        default = next((d for d in devices if d.is_default), devices[0])
        log.info(f"Using default device: {default}")
        return default.index

    def calibrate_noise(self, device_index: Optional[int] = None) -> float:
        """
        Sample ambient noise for dynamic threshold calibration.
        Returns adjusted energy threshold.
        """
        import pyaudio
        self._state = CaptureState.CALIBRATING
        log.info(f"📊 Calibrating ambient noise ({self.config.ambient_noise_duration}s)...")

        frames = []
        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.config.channels,
            rate=self.config.sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self.config.chunk_size,
        )

        n_chunks = int(
            self.config.sample_rate / self.config.chunk_size
            * self.config.ambient_noise_duration
        )
        for _ in range(n_chunks):
            try:
                data = stream.read(self.config.chunk_size, exception_on_overflow=False)
                frames.append(data)
            except Exception:
                break

        stream.stop_stream()
        stream.close()

        all_audio = b"".join(frames)
        ambient_rms = _compute_rms(all_audio, self.config.sample_width)

        if self.config.dynamic_energy:
            self._energy_threshold = max(
                self.config.energy_threshold,
                int(ambient_rms * self.config.dynamic_energy_ratio),
            )

        log.info(f"  Ambient RMS: {ambient_rms:.1f} | Threshold set: {self._energy_threshold}")
        self._state = CaptureState.IDLE
        return self._energy_threshold

    def capture(self, device_index: Optional[int] = None) -> Optional[CapturedAudio]:
        """
        Capture one complete speech phrase.
        - Waits for speech (energy above threshold)
        - Records until silence (energy drops below threshold)
        - Applies listen_timeout and phrase_timeout
        Returns CapturedAudio or None on timeout/error.
        """
        import pyaudio
        self._state = CaptureState.LISTENING
        log.info("🎤 Listening... (speak now)")

        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.config.channels,
            rate=self.config.sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self.config.chunk_size,
        )

        frames = []
        silence_chunks = 0
        speech_started = False
        start_time = time.time()
        peak_energy = 0.0

        silence_chunk_limit = int(
            self.config.pause_threshold
            * self.config.sample_rate
            / self.config.chunk_size
        )

        try:
            while True:
                elapsed = time.time() - start_time

                # Timeout: waiting for speech to start
                if not speech_started and elapsed > self.config.listen_timeout:
                    log.warning("⏱️ Listen timeout — no speech detected")
                    self._state = CaptureState.TIMEOUT
                    return None

                # Timeout: phrase too long
                if speech_started and elapsed > self.config.phrase_timeout:
                    log.warning("⏱️ Phrase timeout — cutting off")
                    break

                data = stream.read(self.config.chunk_size, exception_on_overflow=False)
                rms = _compute_rms(data, self.config.sample_width)
                peak_energy = max(peak_energy, rms)
                is_speech = rms > self._energy_threshold

                if is_speech:
                    speech_started = True
                    silence_chunks = 0
                    frames.append(data)
                    if self._state != CaptureState.CAPTURING:
                        self._state = CaptureState.CAPTURING
                        log.debug("🗣️ Speech detected — recording...")
                elif speech_started:
                    frames.append(data)  # Include trailing silence
                    silence_chunks += 1
                    if silence_chunks >= silence_chunk_limit:
                        log.debug("🔇 Silence detected — phrase complete")
                        break

        finally:
            stream.stop_stream()
            stream.close()

        if not frames:
            return None

        raw = b"".join(frames)
        duration = len(raw) / (
            self.config.sample_rate
            * self.config.channels
            * self.config.sample_width
        )

        if duration < self.config.phrase_min_duration:
            log.debug(f"Phrase too short ({duration:.2f}s) — discarded")
            return None

        self._state = CaptureState.IDLE
        log.info(f"✅ Captured {duration:.2f}s of audio | Peak RMS: {peak_energy:.0f}")
        return CapturedAudio(
            frames=raw,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            sample_width=self.config.sample_width,
            duration_seconds=duration,
            peak_energy=peak_energy,
            language_hint=self.config.language.value,
        )

    def stream_chunks(
        self, device_index: Optional[int] = None
    ) -> Generator[AudioChunk, None, None]:
        """
        Stream audio chunks continuously.
        Yields AudioChunk objects — consumer decides when to stop.
        For use with streaming recognition (Phase 3).
        """
        import pyaudio
        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=self.config.channels,
            rate=self.config.sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self.config.chunk_size,
        )
        try:
            while True:
                data = stream.read(self.config.chunk_size, exception_on_overflow=False)
                rms = _compute_rms(data, self.config.sample_width)
                yield AudioChunk(
                    data=data,
                    rms_energy=rms,
                    timestamp=time.time(),
                    is_speech=rms > self._energy_threshold,
                )
        finally:
            stream.stop_stream()
            stream.close()

    def terminate(self):
        if self._pa:
            self._pa.terminate()
            log.debug("PyAudio terminated")


# ── Mock backend (testing / CI) ───────────────────────────────

class MockAudioCapture:
    """
    Deterministic mock audio backend for testing.
    Simulates the full capture pipeline without hardware.
    Generates synthetic PCM audio that mimics real speech.
    """

    def __init__(self, config: AudioConfig, responses: Optional[List[str]] = None):
        self.config = config
        self._responses = responses or [
            "open spotify",
            "set volume to 50",
            "play next song",
            "what is the weather today",
            "set a timer for 5 minutes",
        ]
        self._idx = 0
        self._energy_threshold = config.energy_threshold
        self._state = CaptureState.IDLE
        log.info("🧪 MockAudioCapture initialized (testing mode)")

    def initialize(self) -> bool:
        return True

    def list_devices(self) -> List[AudioDevice]:
        return [
            AudioDevice(0, "Mock Microphone (Default)", 1, 16000.0, True),
            AudioDevice(1, "Mock USB Mic",              1, 44100.0, False),
        ]

    def select_device(self) -> int:
        return 0

    def calibrate_noise(self, device_index=None) -> float:
        log.info("📊 Mock noise calibration complete")
        return self._energy_threshold

    def capture(self, device_index=None) -> Optional[CapturedAudio]:
        """Return synthetic audio that represents the next mock response."""
        self._state = CaptureState.CAPTURING
        time.sleep(0.05)  # Simulate capture delay

        # Generate synthetic silence + speech PCM
        duration = 1.5
        n_samples = int(self.config.sample_rate * duration)

        # Simulate speech: medium energy sine-like waveform
        import struct, math
        frames = []
        for i in range(n_samples):
            # Simulate speech energy (varied amplitude)
            energy = 800 + int(400 * math.sin(2 * math.pi * 200 * i / self.config.sample_rate))
            frames.append(struct.pack("<h", energy))

        raw = b"".join(frames)
        self._state = CaptureState.IDLE

        return CapturedAudio(
            frames=raw,
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            sample_width=self.config.sample_width,
            duration_seconds=duration,
            peak_energy=900.0,
            language_hint=self.config.language.value,
        )

    def stream_chunks(self, device_index=None) -> Generator[AudioChunk, None, None]:
        """Yield a fixed number of mock chunks then stop."""
        for i in range(20):
            import struct, math
            energy = 600 + int(200 * math.sin(i * 0.5))
            data = struct.pack("<h", energy) * self.config.chunk_size
            yield AudioChunk(
                data=data,
                rms_energy=float(energy),
                timestamp=time.time(),
                is_speech=energy > self._energy_threshold,
            )
            time.sleep(0.01)

    def terminate(self):
        pass


# ── Factory ───────────────────────────────────────────────────

def create_capture_backend(config: AudioConfig):
    """
    Factory: returns the best available capture backend.
    Tries PyAudio first, falls back to Mock gracefully.
    """
    if config.backend == AudioBackend.MOCK:
        return MockAudioCapture(config)

    try:
        import pyaudio
        backend = PyAudioCapture(config)
        if backend.initialize():
            return backend
        log.warning("PyAudio available but init failed — using mock")
    except ImportError:
        log.warning("PyAudio not installed — using mock capture backend")

    return MockAudioCapture(config)


__all__ = [
    "AudioChunk", "CapturedAudio", "AudioDevice", "CaptureState",
    "PyAudioCapture", "MockAudioCapture", "create_capture_backend",
]
