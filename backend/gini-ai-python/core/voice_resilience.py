# ============================================================
# GINI-ORACLE-1 — Voice Resilience
# core/voice_resilience.py
# ============================================================
"""
Resilience layer for voice operations:
  - Microphone failure recovery
  - STT (Speech-to-Text) timeout handling
  - TTS (Text-to-Speech) crash recovery
  - Audio device fallback

Strategies:
  1. Mic Failure → Try alternative devices, fallback to text input
  2. STT Timeout → Extend timeout, try faster model, fallback to text
  3. TTS Crash → Log error, continue with text output, disable TTS temporarily
  4. Device Not Found → Use default device, list available devices
"""

import asyncio
from dataclasses import dataclass
from typing import Optional, List, Callable
from enum import Enum

from utils.logger import get_logger
from utils.event_logger import get_event_logger
from core.resilience import (
    FailureMode, RecoveryStrategy, FailureContext, 
    RetryPolicy, get_recovery_manager
)

log = get_logger(__name__)
elog = get_event_logger()


class VoiceFailureMode(str, Enum):
    """Voice-specific failures."""
    MIC_NOT_FOUND = "mic_not_found"
    MIC_PERMISSION_DENIED = "mic_permission_denied"
    MIC_BUSY = "mic_busy"
    STT_TIMEOUT = "stt_timeout"
    STT_ERROR = "stt_error"
    TTS_CRASH = "tts_crash"
    TTS_DISABLED = "tts_disabled"
    AUDIO_FORMAT_ERROR = "audio_format_error"


@dataclass
class VoiceRecoveryAction:
    """Suggested recovery action for voice failure."""
    fallback_mode: str  # "text_input", "try_device_X", "use_faster_model"
    user_message: str
    can_retry: bool
    suggested_timeout: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "fallback_mode": self.fallback_mode,
            "message": self.user_message,
            "can_retry": self.can_retry,
            "suggested_timeout": self.suggested_timeout,
        }


class VoiceResilienceManager:
    """Handles voice pipeline resilience."""

    def __init__(self):
        self.recovery_manager = get_recovery_manager()
        self.mic_available = False
        self.tts_enabled = True
        self.stt_enabled = True
        self.fallback_language = "en-US"
        self.retry_policy = RetryPolicy(
            max_attempts=3,
            initial_delay=0.5,
            max_delay=5.0,
        )
        
        # Register circuits for voice services
        self.recovery_manager.register_circuit(
            "microphone",
            failure_threshold=3,
            recovery_timeout=10,
        )
        self.recovery_manager.register_circuit(
            "speech_recognizer",
            failure_threshold=2,
            recovery_timeout=5,
        )
        self.recovery_manager.register_circuit(
            "text_to_speech",
            failure_threshold=2,
            recovery_timeout=15,
        )
        
        log.info("🎤 VoiceResilienceManager initialized")
        elog.lifecycle("voice_resilience", "complete", component="VoiceResilienceManager")

    # ── Microphone Recovery ───────────────────────────────────

    async def handle_mic_failure(
        self,
        error: str,
        available_devices: Optional[List[str]] = None,
    ) -> VoiceRecoveryAction:
        """
        Handle microphone failure with recovery suggestions.
        
        Returns VoiceRecoveryAction with recommended fallback.
        """
        log.error(f"🎤❌ Microphone failure: {error}")
        elog.voice_event(
            "mic_failure",
            error=error,
            metadata={"available_devices": available_devices or []},
        )
        
        circuit = self.recovery_manager.get_circuit("microphone")
        if circuit:
            circuit.failure_count += 1

        # Categorize error
        if "permission" in error.lower():
            return VoiceRecoveryAction(
                fallback_mode="text_input",
                user_message="Microphone permission denied. Using text input mode.",
                can_retry=True,
            )
        elif "not found" in error.lower() or "no device" in error.lower():
            if available_devices and len(available_devices) > 0:
                return VoiceRecoveryAction(
                    fallback_mode="try_device_0",
                    user_message=f"Microphone not found. Trying device: {available_devices[0]}",
                    can_retry=True,
                )
            else:
                return VoiceRecoveryAction(
                    fallback_mode="text_input",
                    user_message="No microphones found. Switched to text input.",
                    can_retry=True,
                )
        elif "busy" in error.lower() or "in use" in error.lower():
            return VoiceRecoveryAction(
                fallback_mode="wait_and_retry",
                user_message="Microphone is in use. Retrying in a moment...",
                can_retry=True,
            )
        else:
            return VoiceRecoveryAction(
                fallback_mode="text_input",
                user_message=f"Microphone error: {error[:50]}. Using text input.",
                can_retry=True,
            )

    # ── STT Timeout Recovery ──────────────────────────────────

    async def handle_stt_timeout(
        self,
        current_timeout: float,
        max_timeout: float = 30.0,
    ) -> VoiceRecoveryAction:
        """
        Handle speech recognition timeout.
        
        Strategies:
        1. Increase timeout
        2. Try faster model
        3. Fall back to text input
        """
        log.warning(f"⏱️❌ STT timeout (current: {current_timeout}s)")
        elog.voice_event(
            "stt_timeout",
            error=f"Timeout after {current_timeout}s",
            metadata={"current_timeout": current_timeout, "max_timeout": max_timeout},
        )

        circuit = self.recovery_manager.get_circuit("speech_recognizer")
        if circuit:
            circuit.failure_count += 1

        if current_timeout < max_timeout * 0.5:
            new_timeout = current_timeout * 1.5
            return VoiceRecoveryAction(
                fallback_mode="retry_with_timeout",
                user_message=f"Listening timeout increased. Please speak louder or closer to microphone.",
                can_retry=True,
                suggested_timeout=new_timeout,
            )
        else:
            return VoiceRecoveryAction(
                fallback_mode="text_input",
                user_message="Could not hear you. Please use text input or try again.",
                can_retry=True,
            )

    # ── TTS Crash Recovery ────────────────────────────────────

    async def handle_tts_crash(self, error: str) -> VoiceRecoveryAction:
        """
        Handle text-to-speech crash.
        
        Strategies:
        1. Log error, disable TTS temporarily
        2. Continue with text output
        3. Try to reinitialize TTS
        """
        log.error(f"🔊❌ TTS crash: {error}")
        elog.voice_event("tts_crash", error=error, recovery="text_only")

        circuit = self.recovery_manager.get_circuit("text_to_speech")
        if circuit:
            circuit.failure_count += 1

        self.tts_enabled = False
        
        return VoiceRecoveryAction(
            fallback_mode="text_only",
            user_message="Voice output temporarily disabled. Using text only.",
            can_retry=True,
        )

    # ── STT Error Recovery ────────────────────────────────────

    async def handle_stt_error(
        self,
        error: str,
        attempt: int = 1,
        max_attempts: int = 3,
    ) -> VoiceRecoveryAction:
        """Handle speech recognition error with retry."""
        log.error(f"🎙️❌ STT error (attempt {attempt}): {error}")
        elog.voice_event(
            "stt_error",
            error=error,
            metadata={"attempt": attempt, "max_attempts": max_attempts},
        )

        circuit = self.recovery_manager.get_circuit("speech_recognizer")
        if circuit:
            circuit.failure_count += 1

        if attempt < max_attempts:
            return VoiceRecoveryAction(
                fallback_mode="retry_stt",
                user_message=f"Could not recognize speech. Please try again. (Attempt {attempt})",
                can_retry=True,
            )
        else:
            return VoiceRecoveryAction(
                fallback_mode="text_input",
                user_message="Could not recognize speech after multiple attempts. Please use text input.",
                can_retry=False,
            )

    # ── Audio Device Management ────────────────────────────────

    async def detect_audio_devices(self) -> List[str]:
        """Detect available audio devices."""
        log.info("🔍 Detecting audio devices...")
        elog.voice_event("device_detection", metadata={"action": "detect"})
        # This would call into the voice engine to list devices
        # For now, returning placeholder
        return ["default", "alternate"]

    async def switch_audio_device(self, device_index: int) -> bool:
        """Attempt to switch to alternative audio device."""
        log.info(f"🔄 Switching to audio device {device_index}...")
        elog.voice_event("device_switch", device=str(device_index))
        try:
            # This would reinitialize the capture backend with new device
            await asyncio.sleep(0.5)  # Simulate device switch
            elog.voice_event("device_switch_success", device=str(device_index))
            return True
        except Exception as e:
            log.error(f"Failed to switch device: {e}")
            elog.voice_event("device_switch", device=str(device_index), error=str(e))
            return False

    # ── TTS Reinitialization ──────────────────────────────────

    async def reinitialize_tts(self) -> bool:
        """Attempt to reinitialize TTS system."""
        log.info("🔄 Attempting to reinitialize TTS...")
        elog.voice_event("tts_reinit_start")
        try:
            await asyncio.sleep(1)  # Simulate reinitialization
            self.tts_enabled = True
            log.info("✅ TTS reinitialized")
            elog.voice_event("tts_reinit_success")
            return True
        except Exception as e:
            log.error(f"TTS reinitialization failed: {e}")
            elog.voice_event("tts_reinit_failed", error=str(e))
            return False

    # ── Status and Diagnostics ────────────────────────────────

    def get_status(self) -> dict:
        """Get voice system status."""
        return {
            "mic_available": self.mic_available,
            "tts_enabled": self.tts_enabled,
            "stt_enabled": self.stt_enabled,
            "circuits": {
                "microphone": self.recovery_manager.get_circuit("microphone").status(),
                "stt": self.recovery_manager.get_circuit("speech_recognizer").status(),
                "tts": self.recovery_manager.get_circuit("text_to_speech").status(),
            }
        }

    async def self_heal(self) -> dict:
        """Attempt to self-heal voice system."""
        log.info("🏥 Voice system self-healing...")
        
        results = {
            "tts_reinitialized": False,
            "devices_detected": [],
            "status": "degraded",
        }

        # Try to reinitialize TTS
        if not self.tts_enabled:
            results["tts_reinitialized"] = await self.reinitialize_tts()

        # Detect available devices
        results["devices_detected"] = await self.detect_audio_devices()

        # Update status
        if self.tts_enabled and self.mic_available:
            results["status"] = "healthy"
        elif len(results["devices_detected"]) > 0:
            results["status"] = "degraded_but_functional"

        log.info(f"🏥 Self-heal result: {results['status']}")
        return results


# ── Global instance ──────────────────────────────────────

_voice_resilience: Optional[VoiceResilienceManager] = None


def get_voice_resilience() -> VoiceResilienceManager:
    """Get or create global voice resilience manager."""
    global _voice_resilience
    if _voice_resilience is None:
        _voice_resilience = VoiceResilienceManager()
    return _voice_resilience


__all__ = [
    "VoiceResilienceManager",
    "VoiceRecoveryAction",
    "VoiceFailureMode",
    "get_voice_resilience",
]
