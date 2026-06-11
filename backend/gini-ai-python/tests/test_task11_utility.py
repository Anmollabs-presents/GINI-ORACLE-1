import sys, asyncio
sys.path.insert(0, '.')

print('=' * 60)
print('  TASK 11 — UTILITY SUBSYSTEM TESTS')
print('=' * 60)

from actions.command_parser import CommandParser
from actions.handlers.utility_handler import UtilityHandler
from actions.intent_detector import IntentDetector, IntentResult

parser = CommandParser()
detector = IntentDetector()
handler = UtilityHandler()

print()
print('1. IntentDetector — current time/date detection...')

intent_cases = [
    ("what time is it", "utility", "time"),
    ("whats the time", "utility", "time"),
    ("current time", "utility", "time"),
    ("what is the date today", "utility", "date"),
    ("today's date", "utility", "date"),
]
for text, exp_intent, exp_sub in intent_cases:
    cmd = parser.parse(text)
    result = detector.detect(cmd)
    assert result.intent == exp_intent, f'{text} → {result.intent} expected {exp_intent}'
    assert result.sub_intent == exp_sub, f'{text} → {result.sub_intent} expected {exp_sub}'
print('   PASS: intent detection for time/date')

print()
print('2. UtilityHandler — current time/date responses...')

async def run(text, sub):
    cmd = parser.parse(text)
    result = IntentResult("utility", 0.9, sub_intent=sub)
    return await handler.handle(cmd, result)

responses = [
    ("what time is it", "time", "current time is"),
    ("what is the date", "date", "today is"),
]
for text, sub, expected in responses:
    out = asyncio.run(run(text, sub))
    assert out["status"] == "ok"
    assert expected in out["response"].lower()
print('   PASS: utility handler for time/date')

print()
print('3. UtilityHandler — timer, reminder, calculate')

async def test_timer():
    cmd = parser.parse("set a timer for 5 minutes")
    result = IntentResult("utility", 0.9, sub_intent="timer")
    out = await handler.handle(cmd, result)
    assert out["status"] == "ok"
    data = out.get("data", {})
    assert data.get("minutes") == 5
    assert data.get("seconds") == 0
    assert "timer set" in out["response"].lower()

async def test_reminder():
    cmd = parser.parse("remind me to buy milk at 5pm")
    result = IntentResult("utility", 0.9, sub_intent="reminder")
    out = await handler.handle(cmd, result)
    assert out["status"] == "ok"
    data = out.get("data", {})
    assert data.get("task") == "buy milk"
    assert data.get("time")
    assert "reminder set" in out["response"].lower()

async def test_calculator():
    cmd = parser.parse("calculate 3 * 7")
    result = IntentResult("utility", 0.9, sub_intent="calculate")
    out = await handler.handle(cmd, result)
    assert out["status"] == "ok"
    data = out.get("data", {})
    assert data.get("result") == 21
    assert "result is" in out["response"].lower()

asyncio.run(test_timer())
asyncio.run(test_reminder())
asyncio.run(test_calculator())
print('   PASS: timer, reminder, calculate commands')
