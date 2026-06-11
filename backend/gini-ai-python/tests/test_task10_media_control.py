import sys, asyncio
sys.path.insert(0, '.')

print('=' * 60)
print('  TASK 10 — MEDIA CONTROL SUBSYSTEM TESTS')
print('=' * 60)

from actions.handlers.media_control_handler import MediaControlHandler
from actions.command_parser import CommandParser
from actions.intent_detector import IntentResult

handler = MediaControlHandler(mock=True)
parser = CommandParser()

async def run(text, sub=None):
    cmd = parser.parse(text)
    r = IntentResult("media_control", 0.9, sub_intent=sub or "play")
    return await handler.handle(cmd, r)

print()
print('1. MediaControlHandler — basic commands...')

cases = [
    ("play", "play", "Resuming playback."),
    ("pause", "pause", "Paused."),
    ("stop the music", "stop", "Playback stopped."),
    ("next song", "next", "Skipping to the next track."),
    ("previous track", "previous", "Going to the previous track."),
    ("play despacito", "play", "Attempting to play"),
]

passed = 0
for text, sub, expected in cases:
    result = asyncio.run(run(text, sub))
    if expected in result["response"] and result["status"] == "ok":
        passed += 1
    else:
        print(f'   FAIL: "{text}" → {result}')

assert passed == len(cases), f"{passed}/{len(cases)} media commands passed"
print(f'   PASS: {passed}/{len(cases)} basic media commands')

print()
print('2. MockExecutor call recording...')

assert any(call["method"] == "media_play" for call in handler._executor.calls), "media_play not recorded"
assert any(call["method"] == "media_pause" for call in handler._executor.calls), "media_pause not recorded"
assert any(call["method"] == "media_stop" for call in handler._executor.calls), "media_stop not recorded"
assert any(call["method"] == "media_next" for call in handler._executor.calls), "media_next not recorded"
assert any(call["method"] == "media_previous" for call in handler._executor.calls), "media_previous not recorded"

print('   PASS: MockExecutor call recording')
