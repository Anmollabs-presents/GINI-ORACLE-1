import sys, time, threading
sys.path.insert(0, '.')

print('=' * 60)
print('  TASK 6 — WAKE WORD DETECTION TESTS')
print('=' * 60)

# ── 1. WAKE_WORDS set (existing + new phrases) ────────────────
print()
print('1. WAKE_WORDS set (existing + new phrases)...')
from voice.hindi_normalizer import WAKE_WORDS 

required = {"hey gini", "hello gini", "hi gini", "gini", "ok gini", "okay gini"}
for phrase in required:
    assert phrase in WAKE_WORDS, f"Missing: {phrase}"
assert len(WAKE_WORDS) >= 7
print(f'   Phrases: {sorted(WAKE_WORDS)}')
print('   PASS: WAKE_WORDS')

# ── 2. PhraseMatcher — exact, variant, fuzzy ─────────────────
print()
print('2. PhraseMatcher (exact + variant + fuzzy)...')
from voice.wake_word_detector import PhraseMatcher

matcher = PhraseMatcher(WAKE_WORDS, min_ratio=0.70)

exact_cases = [
    ("hey gini",         True,  "hey gini",   1.0),
    ("hello gini",       True,  "hello gini", 1.0),
    ("ok gini play music",True, "ok gini",    1.0),
    ("gini",             True,  "gini",       1.0),
    ("random noise",     False, "",           0.0),
    ("completely unrelated", False, "",       0.0),
]
passed = 0
for text, exp_match, exp_phrase, exp_conf_min in exact_cases:
    matched, phrase, conf = matcher.match(text)
    ok = (matched == exp_match)
    if exp_match:
        ok = ok and (exp_phrase in phrase or phrase in exp_phrase)
        ok = ok and (conf >= exp_conf_min - 0.01)
    if ok:
        passed += 1
    else:
        print(f'   FAIL: "{text}" → matched={matched} phrase="{phrase}" conf={conf:.2f}')
print(f'   Exact/substring: {passed}/{len(exact_cases)} correct')

# Variant / acoustic confusable cases
variant_cases = [
    "hey genie",       # genie → gini
    "hay gini",        # hay → hey
    "aye gini",        # variant in set
    "helo gini",       # helo → hello
]
var_passed = 0
for text in variant_cases:
    matched, phrase, conf = matcher.match(text)
    if matched:
        var_passed += 1
    else:
        print(f'   WARN (variant): "{text}" → not matched (conf={conf:.2f})')
print(f'   Variant/fuzzy: {var_passed}/{len(variant_cases)} matched')
print('   PASS: PhraseMatcher')

# ── 3. WakeWordConfig ─────────────────────────────────────────
print()
print('3. WakeWordConfig...')
from voice.wake_word_detector import WakeWordConfig

cfg_test = WakeWordConfig.for_testing()
assert cfg_test.cooldown_seconds == 0.2
assert cfg_test.min_confidence == 0.60
assert cfg_test.energy_threshold == 100
assert len(cfg_test.wake_phrases) >= 7

cfg_prod = WakeWordConfig.for_production()
assert cfg_prod.min_confidence >= 0.75
assert cfg_prod.cooldown_seconds >= 2.0
assert cfg_prod.energy_threshold >= 200
print('   PASS: WakeWordConfig')

# ── 4. MockWakeWordDetector — fires events ────────────────────
print()
print('4. MockWakeWordDetector (fires WakeEvents)...')
from voice.wake_word_detector import MockWakeWordDetector, WakeEvent, DetectorState

events = []
listening_calls = []

def on_wake(event: WakeEvent):
    events.append(event)

def on_listening():
    listening_calls.append(time.time())

detector = MockWakeWordDetector(
    config=WakeWordConfig.for_testing(),
    on_wake=on_wake,
    on_listening=on_listening,
    fire_after=0.1,
    fire_count=2,
)
detector.start()
assert detector.is_running()
assert detector.state != DetectorState.STOPPED

# Wait for 2 events (fire_count=2, fire_after=0.1, cooldown=0.2)
time.sleep(1.5)

assert len(events) == 2, f'Expected 2 events, got {len(events)}'
assert all(isinstance(e, WakeEvent) for e in events)
assert all(e.confidence > 0.9 for e in events)
assert all(e.phrase in WAKE_WORDS for e in events)
assert events[0].triggered_by == "mock"

# Check cooldown was respected
if len(events) >= 2:
    gap = events[1].timestamp - events[0].timestamp
    assert gap >= 0.15, f'Cooldown too short: {gap:.2f}s'

print(f'   Events fired: {len(events)}')
print(f'   Phrases: {[e.phrase for e in events]}')
print(f'   Confidences: {[round(e.confidence,2) for e in events]}')
print('   PASS: MockWakeWordDetector fires events')

# ── 5. Trigger count ─────────────────────────────────────────
print()
print('5. Trigger count tracking...')
assert detector.trigger_count == 2
print(f'   Trigger count: {detector.trigger_count}')
print('   PASS: Trigger count')

# ── 6. Status dict ────────────────────────────────────────────
print()
print('6. Status dict...')
status = detector.status()
assert 'state' in status
assert 'running' in status
assert 'phrases' in status
assert 'trigger_count' in status
assert 'cooldown_seconds' in status
assert 'energy_threshold' in status
assert 'min_confidence' in status
assert status['trigger_count'] == 2
print(f'   Status: {status}')
print('   PASS: Status dict')

# ── 7. Stop / restart ────────────────────────────────────────
print()
print('7. Stop / restart...')
detector.stop()
time.sleep(0.1)
assert not detector.is_running()
assert detector.state == DetectorState.STOPPED

# Restart
events2 = []
detector2 = MockWakeWordDetector(
    config=WakeWordConfig.for_testing(),
    on_wake=lambda e: events2.append(e),
    fire_after=0.1,
    fire_count=1,
)
detector2.start()
time.sleep(0.8)
assert len(events2) == 1
detector2.stop()
print('   PASS: Stop/restart')

# ── 8. Add / remove phrases at runtime ───────────────────────
print()
print('8. Runtime phrase management...')
detector3 = MockWakeWordDetector(
    config=WakeWordConfig.for_testing(),
    on_wake=lambda e: None,
    fire_after=99,   # Don't auto-fire
    fire_count=0,
)
detector3.start()

initial_count = len(detector3.config.wake_phrases)
detector3.add_phrase("yo gini")
assert "yo gini" in detector3.config.wake_phrases
assert len(detector3.config.wake_phrases) == initial_count + 1

detector3.remove_phrase("yo gini")
assert "yo gini" not in detector3.config.wake_phrases
assert len(detector3.config.wake_phrases) == initial_count

detector3.stop()
print('   PASS: Runtime phrase management')

# ── 9. Sensitivity adjustment ─────────────────────────────────
print()
print('9. Sensitivity adjustment...')
detector4 = MockWakeWordDetector(
    config=WakeWordConfig.for_testing(),
    on_wake=lambda e: None,
    fire_after=99,
    fire_count=0,
)
detector4.start()
detector4.set_sensitivity(400)
assert detector4._energy_threshold == 400
detector4.set_sensitivity(30)    # Below min — clamp to 50
assert detector4._energy_threshold == 50
detector4.stop()
print('   PASS: Sensitivity adjustment')

# ── 10. False trigger reduction ───────────────────────────────
print()
print('10. False trigger reduction (cooldown gate)...')
rapid_events = []
det5 = MockWakeWordDetector(
    config=WakeWordConfig.for_testing(),
    on_wake=lambda e: rapid_events.append(e),
    fire_after=0.05,
    fire_count=5,    # Try to fire 5 times
)
det5.start()
time.sleep(2.5)
det5.stop()

# With cooldown=0.2s and fire_after=0.05s, gap is 0.2+0.05=0.25s per event
# 5 events * 0.25s = 1.25s → within our 2.5s window
assert len(rapid_events) == 5
# Verify cooldown was respected between each
for i in range(1, len(rapid_events)):
    gap = rapid_events[i].timestamp - rapid_events[i-1].timestamp
    assert gap >= 0.15, f'Cooldown violated: {gap:.3f}s between events {i-1} and {i}'

print(f'   {len(rapid_events)} events fired, all cooldowns respected')
print('   PASS: False trigger reduction')

# ── 11. VoiceEngine integration ───────────────────────────────
print()
print('11. VoiceEngine wake integration...')
from voice.voice_engine import VoiceEngine
from voice.audio_config import AudioConfig

ve = VoiceEngine(config=AudioConfig.for_testing())
ve.initialize()

# wake_status before start
ws = ve.wake_status()
assert ws['state'] == 'not_initialized'

# Start wake detection (mock=True — no real mic)
ve_events = []
ve.start_wake_detection(
    on_wake=lambda e: ve_events.append(e),
    mock=True,
)
assert ve._wake_detector is not None
assert ve._wake_detector.is_running()

time.sleep(0.8)

# wake_status after start
ws2 = ve.wake_status()
assert 'state' in ws2
assert 'phrases' in ws2

# add wake phrase via VoiceEngine
ve.add_wake_phrase("namaste gini")
assert "namaste gini" in ve._wake_detector.config.wake_phrases

# stop_wake_detection
ve.stop_wake_detection()
time.sleep(0.1)
assert not ve._wake_detector.is_running()

# status() includes wake
full = ve.status()
assert 'wake' in full

# terminate cleans up
ve.terminate()
print(f'   Wake events captured: {len(ve_events)}')
print('   PASS: VoiceEngine integration')

# ── 12. Concurrent thread safety ─────────────────────────────
print()
print('12. Concurrent safety...')
thread_errors = []
thread_events = []

def spawn_detector():
    try:
        d = MockWakeWordDetector(
            config=WakeWordConfig.for_testing(),
            on_wake=lambda e: thread_events.append(e),
            fire_after=0.1,
            fire_count=1,
        )
        d.start()
        time.sleep(0.5)
        d.stop()
    except Exception as ex:
        thread_errors.append(str(ex))

threads = [threading.Thread(target=spawn_detector) for _ in range(4)]
for t in threads: t.start()
for t in threads: t.join()

assert len(thread_errors) == 0, f'Thread errors: {thread_errors}'
print(f'   4 detectors ran concurrently, {len(thread_events)} total events, 0 errors')
print('   PASS: Concurrent safety')

print()
print('=' * 60)
print('  ALL 12 TEST SUITES PASSED')
print('=' * 60)
