# ============================================================
# GINI-ORACLE-1 — Audio Preprocessor
# voice/audio_preprocessor.py
# ============================================================
"""
Applies preprocessing to raw CapturedAudio before recognition:
  1. High-pass filter     — remove low-frequency rumble (A/C hum etc.)
  2. Noise reduction      — spectral subtraction using numpy
  3. Volume normalization — bring audio to consistent level
  4. Trim silence         — remove leading/trailing silence

All operations are numpy-based (no heavy deps).
Falls back to identity transform if numpy unavailable.
"""

import struct
import math
from typing import Tuple
from voice.audio_capture import CapturedAudio
from voice.audio_config import AudioConfig
from utils.logger import get_logger

log = get_logger(__name__)


def _pcm_to_samples(data: bytes, sample_width: int = 2) -> list:
    """Convert raw PCM bytes to list of int16 samples."""
    n = len(data) // sample_width
    return list(struct.unpack(f"{n}h", data[:n * sample_width]))


def _samples_to_pcm(samples: list) -> bytes:
    """Convert list of int16 samples back to raw PCM bytes."""
    # Clamp to int16 range
    clamped = [max(-32768, min(32767, int(s))) for s in samples]
    return struct.pack(f"{len(clamped)}h", *clamped)


def _rms(samples: list) -> float:
    if not samples:
        return 0.0
    mean_sq = sum(s * s for s in samples) / len(samples)
    return math.sqrt(mean_sq)


class AudioPreprocessor:
    """
    Stateless audio preprocessor.
    Each method returns a new CapturedAudio — originals are not mutated.
    """

    def __init__(self, config: AudioConfig):
        self.config = config
        self._numpy_available = self._check_numpy()

    def _check_numpy(self) -> bool:
        try:
            import numpy
            return True
        except ImportError:
            return False

    def process(self, audio: CapturedAudio) -> CapturedAudio:
        """
        Run the full preprocessing chain on a CapturedAudio.
        Skips steps based on config flags.
        Steps: high-pass → noise reduction → normalize → trim
        """
        log.debug(f"Preprocessing {audio.duration_seconds:.2f}s audio...")

        frames = audio.frames

        if self.config.high_pass_filter:
            frames = self._high_pass_filter(frames, audio.sample_rate, audio.sample_width)

        if self.config.noise_reduction and self._numpy_available:
            frames = self._spectral_noise_reduction(frames, audio.sample_rate, audio.sample_width)

        if self.config.normalize_audio:
            frames = self._normalize(frames, audio.sample_width)

        frames = self._trim_silence(frames, audio.sample_width)

        duration = len(frames) / (
            audio.sample_rate * audio.channels * audio.sample_width
        )

        log.debug(f"Preprocessing complete | {audio.duration_seconds:.2f}s → {duration:.2f}s")

        return CapturedAudio(
            frames=frames,
            sample_rate=audio.sample_rate,
            channels=audio.channels,
            sample_width=audio.sample_width,
            duration_seconds=duration,
            peak_energy=audio.peak_energy,
            language_hint=audio.language_hint,
        )

    def _high_pass_filter(self, data: bytes, sample_rate: int, sample_width: int) -> bytes:
        """
        Simple first-order high-pass filter.
        Removes low-frequency hum (A/C, traffic rumble < ~80Hz).
        Uses IIR: y[n] = alpha * (y[n-1] + x[n] - x[n-1])
        """
        try:
            samples = _pcm_to_samples(data, sample_width)
            if len(samples) < 2:
                return data

            # Cutoff ~80Hz
            cutoff = 80.0
            rc = 1.0 / (2 * math.pi * cutoff)
            dt = 1.0 / sample_rate
            alpha = rc / (rc + dt)

            filtered = [0.0] * len(samples)
            filtered[0] = float(samples[0])
            for i in range(1, len(samples)):
                filtered[i] = alpha * (filtered[i-1] + samples[i] - samples[i-1])

            return _samples_to_pcm(filtered)
        except Exception as e:
            log.debug(f"High-pass filter skipped: {e}")
            return data

    def _spectral_noise_reduction(
        self, data: bytes, sample_rate: int, sample_width: int
    ) -> bytes:
        """
        Spectral subtraction noise reduction using numpy FFT.
        Estimates noise floor from the first 0.2s (assumed silence/ambient).
        Subtracts noise spectrum from signal spectrum.
        """
        try:
            import numpy as np

            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if len(samples) < sample_rate * 0.4:
                return data  # Too short to estimate noise

            # Estimate noise from first 200ms
            noise_samples = int(sample_rate * 0.2)
            noise_profile = samples[:noise_samples]

            # FFT-based spectral subtraction
            n_fft = 512
            hop = n_fft // 2

            noise_spectrum = np.abs(np.fft.rfft(noise_profile[:n_fft], n=n_fft))

            output = np.zeros_like(samples)
            for start in range(0, len(samples) - n_fft, hop):
                frame = samples[start:start + n_fft]
                spectrum = np.fft.rfft(frame)
                magnitude = np.abs(spectrum)
                phase = np.angle(spectrum)

                # Subtract noise floor (with floor at 0.1 to avoid musical noise)
                reduced = np.maximum(magnitude - noise_spectrum, 0.1 * magnitude)
                clean = np.fft.irfft(reduced * np.exp(1j * phase))
                output[start:start + n_fft] += clean

            # Normalize output to original scale
            peak = np.max(np.abs(output))
            if peak > 0:
                orig_peak = np.max(np.abs(samples))
                output = output * (orig_peak / peak)

            result = np.clip(output, -32768, 32767).astype(np.int16)
            return result.tobytes()

        except Exception as e:
            log.debug(f"Spectral noise reduction skipped: {e}")
            return data

    def _normalize(self, data: bytes, sample_width: int) -> bytes:
        """
        Normalize audio volume to a consistent level.
        Scales so the peak sample hits ~90% of max (29491 / 32768).
        """
        try:
            samples = _pcm_to_samples(data, sample_width)
            if not samples:
                return data

            peak = max(abs(s) for s in samples)
            if peak == 0:
                return data

            target = 29491  # 90% of int16 max
            scale = target / peak
            normalized = [s * scale for s in samples]
            return _samples_to_pcm(normalized)
        except Exception as e:
            log.debug(f"Normalization skipped: {e}")
            return data

    def _trim_silence(
        self, data: bytes, sample_width: int, window_ms: int = 20
    ) -> bytes:
        """
        Trim leading and trailing silence based on RMS energy.
        Uses a sliding window of window_ms milliseconds.
        """
        try:
            samples = _pcm_to_samples(data, sample_width)
            if not samples:
                return data

            window = max(1, len(samples) * window_ms // 1000)
            threshold = self.config.energy_threshold * 0.5

            # Find start
            start = 0
            for i in range(0, len(samples) - window, window):
                chunk = samples[i:i + window]
                if _rms(chunk) > threshold:
                    start = max(0, i - window)
                    break

            # Find end
            end = len(samples)
            for i in range(len(samples) - window, start, -window):
                chunk = samples[i:i + window]
                if _rms(chunk) > threshold:
                    end = min(len(samples), i + window)
                    break

            trimmed = samples[start:end]
            if len(trimmed) < window:
                return data  # Don't over-trim very short clips

            return _samples_to_pcm(trimmed)
        except Exception as e:
            log.debug(f"Silence trim skipped: {e}")
            return data

    def get_audio_stats(self, audio: CapturedAudio) -> dict:
        """Return diagnostic statistics for a CapturedAudio."""
        try:
            samples = _pcm_to_samples(audio.frames, audio.sample_width)
            rms = _rms(samples)
            peak = max(abs(s) for s in samples) if samples else 0
            return {
                "duration_s": round(audio.duration_seconds, 3),
                "sample_count": len(samples),
                "rms_energy": round(rms, 1),
                "peak_amplitude": peak,
                "dynamic_range_db": round(20 * math.log10(peak / rms) if rms > 0 else 0, 1),
                "sample_rate": audio.sample_rate,
                "language_hint": audio.language_hint,
            }
        except Exception:
            return {"duration_s": audio.duration_seconds}


__all__ = ["AudioPreprocessor"]
