import sys, asyncio, time, threading, wave, io
sys.path.insert(0, '.')

print('=' * 58)
print('  TASK 5 — SPEECH OUTPUT SUBSYSTEM TESTS')
print('=' * 58)

# ── 1. TTSConfig ──────────────────────────────────────────────
print()
print('1. TTSConfig...')
from voice.tts_config import TTSConfig, TTSBackend, VoiceGender, TTSLanguage
cfg = TTSConfig.for_testing()
assert cfg.backend == TTSBackend.MOCK
assert cfg.queue_maxsize == 5
assert cfg.rate == 200
cfg2 = TTSConfig.for_pyttsx3(VoiceGender.FEMALE)
assert cfg2.backend == TTSBackend.PYTTSX3
cfg3 = TTSConfig.for_gtts(TTSLanguage.HINDI)
assert cfg3.backend == TTSBackend.GTTS
assert cfg.allow_interrupt == True
print('   PASS: TTSConfig')

# ── 2. MockTTSEngine ──────────────────────────────────────────
print()
print('2. MockTTSEngine...')
from voice.tts_engine import MockTTSEngine, create_tts_engine, SynthesisResult
engine = MockTTSEngine(cfg)
assert engine.load() == True
voices = engine.list_voices()
assert len(voices) >= 1
result = engine.synthesize('Hello, I am Gini your AI assistant.')
assert result.success == True
assert result.has_audio == True
assert result.backend == 'mock'
assert result.duration_ms > 0
with wave.open(io.BytesIO(result.audio_bytes), 'rb') as wf:
    assert wf.getnchannels() == 1
    assert wf.getsampwidth() == 2
    assert wf.getframerate() == 22050
    assert wf.getnframes() > 0
factory_engine = create_tts_engine(cfg)
assert isinstance(factory_engine, MockTTSEngine)
print('   PASS: MockTTSEngine (real WAV verified)')

# ── 3. TextPreprocessor ───────────────────────────────────────
print()
print('3. TextPreprocessor...')
from voice.voice_output_manager import TextPreprocessor
tp = TextPreprocessor(max_chunk_len=80)
chunks = tp.chunk('Hello world.')
assert chunks == ['Hello world.']
long = 'This is sentence one. This is sentence two. This is sentence three. And a fourth one here.'
chunks = tp.chunk(long)
assert len(chunks) >= 1
assert all(len(c) <= 80 for c in chunks)
assert tp.chunk('') == []
assert tp.chunk('   ') == []
chunks2 = tp.chunk('**Bold text** and code here.')
assert '**' not in chunks2[0]
print(f'   Long text split into {len(chunks)} chunk(s)')
print('   PASS: TextPreprocessor')

# ── 4. VoiceOutputManager core ───────────────────────────────
print()
print('4. VoiceOutputManager (queue + worker)...')
from voice.voice_output_manager import VoiceOutputManager, SpeechPriority, OutputState
mgr = VoiceOutputManager(config=TTSConfig.for_testing())
mgr.start()
assert mgr._running == True
mgr.speak('Hello from Gini.', SpeechPriority.NORMAL)
mgr.speak('Second message.')
mgr.speak('Third message.')
done = mgr.wait_until_done(timeout=15.0)
assert done == True
assert mgr.state == OutputState.IDLE
print('   PASS: speak() + queue + worker')

# ── 5. Interruption ───────────────────────────────────────────
print()
print('5. Interruption...')
mgr2 = VoiceOutputManager(config=TTSConfig.for_testing())
mgr2.start()
mgr2.speak('This is a very long message that should be interrupted soon.')
time.sleep(0.05)
mgr2.stop()
time.sleep(0.25)
assert mgr2.state in (OutputState.IDLE, OutputState.INTERRUPTED)
assert mgr2.queue_size == 0
print('   PASS: Interruption')

# ── 6. Priority speech ────────────────────────────────────────
print()
print('6. Priority speech...')
mgr3 = VoiceOutputManager(config=TTSConfig.for_testing())
mgr3.start()
mgr3.speak('Background message one.')
mgr3.speak('Background message two.')
mgr3.speak_priority('URGENT: alert!')
time.sleep(0.1)
done3 = mgr3.wait_until_done(timeout=15.0)
assert done3 == True
print('   PASS: Priority speech')

# ── 7. Hot-swap settings ──────────────────────────────────────
print()
print('7. Hot-swap settings...')
mgr4 = VoiceOutputManager(config=TTSConfig.for_testing())
mgr4.start()
mgr4.set_rate(220);  assert mgr4.config.rate == 220
mgr4.set_rate(50);   assert mgr4.config.rate == 80    # clamped
mgr4.set_rate(500);  assert mgr4.config.rate == 400   # clamped
mgr4.set_volume(0.7); assert abs(mgr4.config.volume - 0.7) < 0.001
mgr4.set_volume(1.5); assert mgr4.config.volume == 1.0   # clamped
mgr4.set_volume(-0.5); assert mgr4.config.volume == 0.0  # clamped
mgr4.set_voice('mock-female'); assert mgr4.config.voice_id == 'mock-female'
voices4 = mgr4.list_voices(); assert isinstance(voices4, list)
print('   PASS: Hot-swap settings')

# ── 8. Pause / resume ─────────────────────────────────────────
print()
print('8. Pause / resume...')
mgr5 = VoiceOutputManager(config=TTSConfig.for_testing())
mgr5.start()
mgr5.pause()
assert not mgr5._pause_event.is_set()
mgr5.speak('Paused message.')
time.sleep(0.1)
mgr5.resume()
assert mgr5._pause_event.is_set()
done5 = mgr5.wait_until_done(timeout=15.0)
assert done5 == True
print('   PASS: Pause/resume')

# ── 9. Status dict ────────────────────────────────────────────
print()
print('9. Status dict...')
status = mgr4.status()
for key in ['state','is_speaking','queue_size','backend','rate','volume','player']:
    assert key in status, f'Missing key: {key}'
print(f'   Status: {status}')
print('   PASS: Status dict')

# ── 10. VoiceEngine integration ───────────────────────────────
print()
print('10. VoiceEngine.speak() integration...')
from voice.voice_engine import VoiceEngine
from voice.audio_config import AudioConfig
ve = VoiceEngine(config=AudioConfig.for_testing())
ve.initialize()
ve.speak('Hello, I am Gini.')
assert ve._output_manager is not None
assert ve.tts_status()['state'] is not None
ve.speak_priority('Alert!')
ve.set_speech_rate(200);  assert ve._output_manager.config.rate == 200
ve.set_speech_volume(0.8); assert abs(ve._output_manager.config.volume - 0.8) < 0.001
ve.set_voice('mock-female'); assert ve._output_manager.config.voice_id == 'mock-female'
assert isinstance(ve.list_voices(), list)
assert isinstance(ve.is_speaking, bool)
ve.stop_speaking()
full_status = ve.status()
assert 'tts' in full_status
assert 'is_speaking' in full_status
ve.terminate()
print('   PASS: VoiceEngine integration')

# ── 11. Concurrent safety ─────────────────────────────────────
print()
print('11. Concurrent safety (8 threads)...')
mgr6 = VoiceOutputManager(config=TTSConfig.for_testing())
mgr6.start()
errors = []

def do_speak(i):
    try:
        mgr6.speak(f'Concurrent message {i}.')
    except Exception as e:
        errors.append(str(e))

threads = [threading.Thread(target=do_speak, args=(i,)) for i in range(8)]
for t in threads: t.start()
for t in threads: t.join()
assert len(errors) == 0, f'Errors: {errors}'
done6 = mgr6.wait_until_done(timeout=20.0)
assert done6 == True
print(f'   PASS: Concurrent safety (8 threads, 0 errors)')

# cleanup
for m in [mgr, mgr2, mgr3, mgr4, mgr5, mgr6]:
    try: m.stop_worker()
    except: pass

print()
print('=' * 58)
print('  ALL 11 TEST SUITES PASSED')
print('=' * 58)
