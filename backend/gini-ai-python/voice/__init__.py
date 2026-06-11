# voice/__init__.py
from .voice_engine import VoiceEngine, VoiceResult
from .audio_config import AudioConfig, AudioBackend, Language
from .audio_capture import CapturedAudio, AudioDevice, create_capture_backend
from .audio_preprocessor import AudioPreprocessor
from .speech_recognizer import RecognitionResult, RecognitionStatus, create_recognizer
from .hindi_normalizer import HindiNormalizer
from .tts_config import TTSConfig, TTSBackend, VoiceGender, TTSLanguage
from .tts_engine import SynthesisResult, VoiceInfo, create_tts_engine
from .voice_output_manager import VoiceOutputManager, SpeechPriority, OutputState, TextPreprocessor
from .wake_word_detector import (
    WakeWordDetector, MockWakeWordDetector,
    WakeWordConfig, WakeEvent, DetectorState, PhraseMatcher,
)

__all__ = [
    # STT pipeline
    "VoiceEngine", "VoiceResult",
    "AudioConfig", "AudioBackend", "Language",
    "CapturedAudio", "AudioDevice", "create_capture_backend",
    "AudioPreprocessor",
    "RecognitionResult", "RecognitionStatus", "create_recognizer",
    "HindiNormalizer",
    # TTS pipeline
    "TTSConfig", "TTSBackend", "VoiceGender", "TTSLanguage",
    "SynthesisResult", "VoiceInfo", "create_tts_engine",
    "VoiceOutputManager", "SpeechPriority", "OutputState", "TextPreprocessor",
    # Wake word detection
    "WakeWordDetector", "MockWakeWordDetector",
    "WakeWordConfig", "WakeEvent", "DetectorState", "PhraseMatcher",
]
