# ============================================================
# GINI-ORACLE-1 — Voice Output Manager
# voice/voice_output_manager.py
# ============================================================
"""
Manages all speech output for Gini.ai.

Responsibilities:
  - Thread-safe speech queue (FIFO)
  - Background worker thread (non-blocking speak calls)
  - Interruption support (stop mid-sentence instantly)
  - Priority speech (e.g. alerts jump the queue)
  - Text preprocessing (chunking long text, punctuation pauses)
  - Voice/speed/volume hot-swap at runtime
  - Graceful shutdown

Architecture:
  speak(text)
    → TextPreprocessor.chunk(text)        # split into speakable pieces
    → SpeechQueue.put(chunks)             # thread-safe queue
    → WorkerThread.run()                  # background consumer
        → TTSEngine.synthesize(chunk)     # generate audio
        → AudioPlayer.play(audio_bytes)   # output audio
        → repeat until queue empty or interrupted

Concurrency model:
  - One background worker thread (daemon)
  - threading.Event for interrupt signal
  - threading.Lock for engine settings hot-swap
  - queue.Queue for thread-safe item passing
"""

import re
import time
import threading
import queue
import wave
import io
import struct
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum

from voice.tts_config import TTSConfig, TTSBackend
from voice.tts_engine import create_tts_engine, SynthesisResult, VoiceInfo
from utils.logger import get_logger
from core.voice_resilience import get_voice_resilience

log = get_logger(__name__)


# ── Speech item priorities ────────────────────────────────────
class SpeechPriority(int, Enum):
    LOW     = 3
    NORMAL  = 2
    HIGH    = 1    # Lower number = higher priority
    URGENT  = 0    # Alerts, errors — jump to front


@dataclass(order=True)
class SpeechItem:
    """One unit of speech in the queue."""
    priority: int
    text: str = field(compare=False)
    chunk_index: int = field(compare=False, default=0)
    total_chunks: int = field(compare=False, default=1)
    item_id: str = field(compare=False, default="")


class OutputState(str, Enum):
    IDLE        = "idle"
    SPEAKING    = "speaking"
    INTERRUPTED = "interrupted"
    STOPPED     = "stopped"


# ── Text preprocessor ─────────────────────────────────────────

class TextPreprocessor:
    """
    Splits long text into speakable chunks.
    Handles punctuation pauses, abbreviations, numbers.
    """

    def __init__(self, max_chunk_len: int = 200):
        self.max_chunk_len = max_chunk_len

    def chunk(self, text: str) -> List[str]:
        """
        Split text into chunks at natural sentence boundaries.
        Returns list of strings, each <= max_chunk_len chars.
        """
        text = self._normalize(text)
        if len(text) <= self.max_chunk_len:
            return [text] if text else []

        # Split at sentence boundaries first
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks = []
        current = ""

        for sentence in sentences:
            if len(current) + len(sentence) + 1 <= self.max_chunk_len:
                current = (current + " " + sentence).strip()
            else:
                if current:
                    chunks.append(current)
                # If single sentence is too long, split at comma/clause
                if len(sentence) > self.max_chunk_len:
                    chunks.extend(self._split_long(sentence))
                    current = ""
                else:
                    current = sentence

        if current:
            chunks.append(current)

        return [c for c in chunks if c.strip()]

    def _normalize(self, text: str) -> str:
        """Clean text for natural speech."""
        text = text.strip()
        # Remove markdown formatting
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        text = re.sub(r"`(.+?)`", r"\1", text)
        text = re.sub(r"#+\s*", "", text)
        # Collapse whitespace
        text = re.sub(r"\s+", " ", text)
        return text

    def _split_long(self, text: str) -> List[str]:
        """Split a long sentence at clause boundaries."""
        parts = re.split(r"[,;]\s+", text)
        chunks = []
        current = ""
        for part in parts:
            if len(current) + len(part) + 2 <= self.max_chunk_len:
                current = (current + ", " + part).strip(", ")
            else:
                if current:
                    chunks.append(current)
                current = part
        if current:
            chunks.append(current)
        return chunks


# ── Audio player ──────────────────────────────────────────────

class AudioPlayer:
    """
    Plays WAV audio bytes.
    Uses system audio APIs where available, else logs the output.
    Designed so real audio playback (PyAudio/sounddevice) can
    be plugged in with zero changes to VoiceOutputManager.
    """

    def __init__(self):
        self._playing = False
        self._interrupt = threading.Event()
        self._backend = self._detect_backend()

    def _detect_backend(self) -> str:
        try:
            import pyaudio
            return "pyaudio"
        except ImportError:
            pass
        try:
            import sounddevice
            import numpy
            return "sounddevice"
        except Exception:
            pass
        return "mock"

    def play(self, audio_bytes: bytes, interrupt_event: threading.Event) -> bool:
        """
        Play WAV audio bytes.
        Checks interrupt_event between chunks — stops immediately if set.
        Returns True if played to completion, False if interrupted.
        """
        if not audio_bytes:
            return True

        self._playing = True
        try:
            if self._backend == "pyaudio":
                return self._play_pyaudio(audio_bytes, interrupt_event)
            elif self._backend == "sounddevice":
                return self._play_sounddevice(audio_bytes, interrupt_event)
            else:
                return self._play_mock(audio_bytes, interrupt_event)
        finally:
            self._playing = False

    def _play_pyaudio(self, audio_bytes: bytes, interrupt_event: threading.Event) -> bool:
        import pyaudio
        try:
            buf = io.BytesIO(audio_bytes)
            with wave.open(buf, "rb") as wf:
                pa = pyaudio.PyAudio()
                stream = pa.open(
                    format=pa.get_format_from_width(wf.getsampwidth()),
                    channels=wf.getnchannels(),
                    rate=wf.getframerate(),
                    output=True,
                )
                chunk = 1024
                data = wf.readframes(chunk)
                while data and not interrupt_event.is_set():
                    stream.write(data)
                    data = wf.readframes(chunk)
                stream.stop_stream()
                stream.close()
                pa.terminate()
            return not interrupt_event.is_set()
        except Exception as e:
            log.error(f"PyAudio playback error: {e}")
            return False

    def _play_sounddevice(self, audio_bytes: bytes, interrupt_event: threading.Event) -> bool:
        try:
            import sounddevice as sd
            import numpy as np
            buf = io.BytesIO(audio_bytes)
            with wave.open(buf, "rb") as wf:
                sr = wf.getframerate()
                frames = wf.readframes(wf.getnframes())
                audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            # Play in chunks so interrupt is responsive
            chunk_size = sr // 10  # 100ms chunks
            for i in range(0, len(audio), chunk_size):
                if interrupt_event.is_set():
                    return False
                sd.play(audio[i:i + chunk_size], samplerate=sr)
                sd.wait()
            return not interrupt_event.is_set()
        except Exception as e:
            log.error(f"sounddevice playback error: {e}")
            return False

    def _play_mock(self, audio_bytes: bytes, interrupt_event: threading.Event) -> bool:
        """
        Mock playback — simulates duration from WAV header.
        Checks interrupt every 100ms.
        """
        try:
            buf = io.BytesIO(audio_bytes)
            with wave.open(buf, "rb") as wf:
                duration = wf.getnframes() / wf.getframerate()
        except Exception:
            duration = 0.5

        log.debug(f"🔊 [Mock playback] {duration:.2f}s audio")

        # Sleep in 100ms slices, check interrupt each time
        slept = 0.0
        while slept < duration:
            if interrupt_event.is_set():
                log.debug("Playback interrupted")
                return False
            time.sleep(min(0.1, duration - slept))
            slept += 0.1

        return True

    @property
    def is_playing(self) -> bool:
        return self._playing


# ── Voice Output Manager ──────────────────────────────────────

class VoiceOutputManager:
    """
    Thread-safe speech output manager for Gini.ai.

    Public API:
        speak(text)                  — queue text for speech (non-blocking)
        speak_priority(text)         — jump to front of queue
        stop()                       — interrupt current speech + clear queue
        pause() / resume()           — pause/resume worker
        set_rate(wpm)                — hot-swap speech rate
        set_volume(0.0–1.0)          — hot-swap volume
        set_voice(voice_id)          — hot-swap voice
        list_voices()                — available voices
        wait_until_done()            — block until queue is empty
        is_speaking                  — property
        state                        — current OutputState
    """

    def __init__(self, config: Optional[TTSConfig] = None):
        self.config = config or TTSConfig.for_testing()

        # Engine + player
        self._engine = create_tts_engine(self.config)
        self._player = AudioPlayer()
        self._preprocessor = TextPreprocessor(self.config.max_chunk_length)

        # Threading primitives
        self._queue: queue.PriorityQueue = queue.PriorityQueue(
            maxsize=self.config.queue_maxsize
        )
        self._interrupt_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()          # Not paused initially
        self._settings_lock = threading.Lock()

        # Worker thread
        self._worker: Optional[threading.Thread] = None
        self._running = False

        # State tracking
        self._state = OutputState.IDLE
        self._current_text = ""
        self._item_counter = 0

        log.info(
            f"🔊 VoiceOutputManager initialized | "
            f"backend={self.config.backend.value} | "
            f"player={self._player._backend}"
        )

    # ── Lifecycle ─────────────────────────────────────────────

    def start(self) -> None:
        """Start the background worker thread."""
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="GiniTTSWorker",
            daemon=True,
        )
        self._worker.start()
        log.info("▶ TTS worker thread started")

    def stop_worker(self) -> None:
        """Gracefully stop the worker thread."""
        self._running = False
        self._interrupt_event.set()
        self._pause_event.set()          # Unblock if paused
        # Drain queue to unblock worker
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        self._state = OutputState.STOPPED
        log.info("⏹ TTS worker stopped")

    # ── Public speak API ──────────────────────────────────────

    def speak(self, text: str, priority: SpeechPriority = SpeechPriority.NORMAL) -> None:
        """
        Queue text for speech output. Non-blocking.
        Long text is automatically split into chunks.
        """
        if not text or not text.strip():
            return

        if not self._running:
            self.start()

        chunks = self._preprocessor.chunk(text)
        if not chunks:
            return

        self._item_counter += 1
        item_id = f"item_{self._item_counter}"

        for i, chunk in enumerate(chunks):
            item = SpeechItem(
                priority=priority.value,
                text=chunk,
                chunk_index=i,
                total_chunks=len(chunks),
                item_id=item_id,
            )
            try:
                self._queue.put(item, timeout=self.config.queue_timeout)
            except queue.Full:
                log.warning(f"TTS queue full — dropping chunk: '{chunk[:40]}'")

        log.debug(f"Queued {len(chunks)} chunk(s) | priority={priority.name}")

    def speak_priority(self, text: str) -> None:
        """Interrupt current speech and speak this text immediately."""
        self.stop()
        time.sleep(0.05)  # Brief gap after interrupt
        self.speak(text, priority=SpeechPriority.URGENT)

    def stop(self) -> None:
        """Stop current speech and clear the queue."""
        log.info("🛑 Speech interrupted")
        self._interrupt_event.set()
        self._state = OutputState.INTERRUPTED

        # Drain queue
        drained = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                drained += 1
            except queue.Empty:
                break

        if drained:
            log.debug(f"Cleared {drained} item(s) from queue")

        # Reset interrupt for next utterance (brief delay for player to stop)
        threading.Timer(0.15, self._reset_interrupt).start()

    def pause(self) -> None:
        """Pause speech after the current chunk completes."""
        self._pause_event.clear()
        log.info("⏸ TTS paused")

    def resume(self) -> None:
        """Resume paused speech."""
        self._pause_event.set()
        log.info("▶ TTS resumed")

    def wait_until_done(self, timeout: float = 30.0) -> bool:
        """
        Block until the speech queue is empty.
        Returns True if completed, False if timed out.
        """
        start = time.time()
        while not self._queue.empty() or self._state == OutputState.SPEAKING:
            if time.time() - start > timeout:
                return False
            time.sleep(0.05)
        return True

    # ── Voice settings (hot-swap, thread-safe) ────────────────

    def set_rate(self, rate: int) -> None:
        """Change speech rate (words per minute). Takes effect on next chunk."""
        with self._settings_lock:
            self.config.rate = max(80, min(400, rate))
            if hasattr(self._engine, "set_rate"):
                self._engine.set_rate(self.config.rate)
        log.info(f"Speech rate → {self.config.rate} WPM")

    def set_volume(self, volume: float) -> None:
        """Change volume (0.0–1.0). Takes effect on next chunk."""
        with self._settings_lock:
            self.config.volume = max(0.0, min(1.0, volume))
            if hasattr(self._engine, "set_volume"):
                self._engine.set_volume(self.config.volume)
        log.info(f"Volume → {self.config.volume:.2f}")

    def set_voice(self, voice_id: str) -> None:
        """Switch voice by ID. Takes effect on next chunk."""
        with self._settings_lock:
            self.config.voice_id = voice_id
        log.info(f"Voice → {voice_id}")

    def list_voices(self) -> List[VoiceInfo]:
        """Return available TTS voices from the engine."""
        if hasattr(self._engine, "list_voices"):
            return self._engine.list_voices()
        return []

    # ── State properties ──────────────────────────────────────

    @property
    def is_speaking(self) -> bool:
        return self._state == OutputState.SPEAKING

    @property
    def state(self) -> OutputState:
        return self._state

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def status(self) -> dict:
        return {
            "state":       self._state.value,
            "is_speaking": self.is_speaking,
            "queue_size":  self.queue_size,
            "backend":     self.config.backend.value,
            "rate":        self.config.rate,
            "volume":      self.config.volume,
            "player":      self._player._backend,
        }

    # ── Worker loop ───────────────────────────────────────────

    def _worker_loop(self) -> None:
        """
        Background thread: dequeues speech items and plays them.
        Respects interrupt, pause, and shutdown signals.
        """
        log.debug("TTS worker loop started")

        while self._running:
            try:
                # Block for next item (0.1s timeout to check _running)
                item: SpeechItem = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._state == OutputState.SPEAKING:
                    self._state = OutputState.IDLE
                continue

            # Pause support — blocks here if paused
            self._pause_event.wait()

            # Check interrupt before processing
            if self._interrupt_event.is_set():
                self._queue.task_done()
                continue

            self._state = OutputState.SPEAKING
            self._current_text = item.text

            try:
                self._process_item(item)
            except Exception as e:
                log.error(f"TTS worker error on '{item.text[:40]}': {e}")
            finally:
                self._queue.task_done()

        self._state = OutputState.STOPPED
        log.debug("TTS worker loop exited")

    def _process_item(self, item: SpeechItem) -> None:
        """Synthesize and play one speech item."""
        log.debug(
            f"Speaking chunk [{item.chunk_index+1}/{item.total_chunks}]: "
            f"'{item.text[:50]}'"
        )

        # Synthesize
        with self._settings_lock:
            result: SynthesisResult = self._engine.synthesize(item.text)

        if not result.success or not result.has_audio:
            log.warning(f"Synthesis failed: {result.error}")
            get_voice_resilience().tts_enabled = False
            self._state = OutputState.IDLE
            return

        # Play (checks interrupt every 100ms internally)
        completed = self._player.play(result.audio_bytes, self._interrupt_event)

        if not completed:
            log.debug("Playback interrupted mid-chunk")
            return

        # Inter-sentence pause
        if (
            item.chunk_index < item.total_chunks - 1
            and not self._interrupt_event.is_set()
        ):
            pause_s = self.config.sentence_pause_ms / 1000
            self._interruptible_sleep(pause_s)

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that wakes immediately on interrupt."""
        step = 0.05
        elapsed = 0.0
        while elapsed < seconds and not self._interrupt_event.is_set():
            time.sleep(step)
            elapsed += step

    def _reset_interrupt(self) -> None:
        """Reset interrupt flag so next speak() works normally."""
        self._interrupt_event.clear()
        if self._state == OutputState.INTERRUPTED:
            self._state = OutputState.IDLE


__all__ = ["VoiceOutputManager", "SpeechPriority", "OutputState", "TextPreprocessor"]
