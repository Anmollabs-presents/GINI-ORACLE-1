import sys, os
# Ensure backend package dir is on sys.path so `import voice` works
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from voice.audio_config import AudioConfig
from voice.audio_capture import create_capture_backend
from voice.speech_recognizer import create_recognizer
from voice.tts_engine import create_tts_engine
from voice.tts_config import TTSConfig

cfg = AudioConfig()
cap = create_capture_backend(cfg)
print('capture_backend=', type(cap).__name__)
try:
    devices = cap.list_devices()
    print('devices=', [str(d) for d in devices])
except Exception as e:
    print('devices_list_error=', repr(e))

recog = create_recognizer(cfg)
print('recognizer=', type(recog).__name__)
if hasattr(recog,'load'):
    try:
        print('recognizer.load()=', recog.load())
    except Exception as e:
        print('recognizer.load_error=', repr(e))

tts_cfg = TTSConfig.for_pyttsx3()
tts = create_tts_engine(tts_cfg)
print('tts_engine=', type(tts).__name__)
if hasattr(tts,'load'):
    try:
        loaded = tts.load()
        print('tts.load()=', loaded)
    except Exception as e:
        print('tts.load_error=', repr(e))
try:
    r = tts.synthesize('Hello Gini')
    print('tts.synthesize -> success=', r.success, 'backend=', r.backend, 'audio_len=', len(r.audio_bytes) if r.audio_bytes else None, 'error=', r.error)
except Exception as e:
    print('tts.synthesize_error=', repr(e))
