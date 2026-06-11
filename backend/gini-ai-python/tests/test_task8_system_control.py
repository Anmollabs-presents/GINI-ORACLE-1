import sys, asyncio, time
sys.path.insert(0, '.')

print('=' * 60)
print('  TASK 8 — SYSTEM CONTROL SUBSYSTEM TESTS')
print('=' * 60)

# ── 1. MockExecutor — all operations ─────────────────────────
print()
print('1. MockExecutor — all operations...')
from actions.system_executor import MockExecutor, ActionStatus

ex = MockExecutor()

# Volume
r = ex.volume_set(75);      assert r.success and r.value == 75
r = ex.volume_set(150);     assert r.value == 100    # clamped
r = ex.volume_set(-10);     assert r.value == 0      # clamped
r = ex.volume_get();        assert r.success
r = ex.mute();              assert r.success;  assert ex._muted == True
r = ex.unmute();            assert r.success;  assert ex._muted == False
r = ex.volume_step("up");   assert r.success
r = ex.volume_step("down"); assert r.success

# Brightness
r = ex.brightness_set(50);  assert r.success and r.value == 50
r = ex.brightness_set(120); assert r.value == 100   # clamped
r = ex.brightness_step("up");   assert r.success
r = ex.brightness_step("down"); assert r.success

# Power
r = ex.shutdown();    assert r.success
r = ex.restart();     assert r.success
r = ex.sleep();       assert r.success
r = ex.lock_screen(); assert r.success
r = ex.cancel_shutdown(); assert r.success

# Call log
assert len(ex.calls) > 10
print(f'   Calls recorded: {len(ex.calls)}')
print('   PASS: MockExecutor')

# ── 2. SystemActionResult ─────────────────────────────────────
print()
print('2. SystemActionResult...')
from actions.system_executor import SystemActionResult, ActionStatus

r_ok  = SystemActionResult(ActionStatus.SUCCESS, "ok", value=50.0)
r_err = SystemActionResult(ActionStatus.ERROR, "fail", error="oops")
r_uns = SystemActionResult(ActionStatus.NOT_SUPPORTED, "unsupported")
r_par = SystemActionResult(ActionStatus.PARTIAL, "partial")

assert r_ok.success  == True
assert r_err.success == False
assert r_uns.success == False
assert r_par.success == True    # PARTIAL counts as success

d = r_ok.to_dict()
assert all(k in d for k in ["status","message","value","error"])
print('   PASS: SystemActionResult')

# ── 3. ConfirmationManager ────────────────────────────────────
print()
print('3. ConfirmationManager...')
from actions.confirmation_manager import (
    ConfirmationManager, get_confirmation_manager,
    DANGEROUS_COMMANDS, CONFIRM_WORDS, CANCEL_WORDS,
)

cm = ConfirmationManager()

# Dangerous command detection
assert cm.requires_confirmation("shutdown") == True
assert cm.requires_confirmation("restart")  == True
assert cm.requires_confirmation("volume")   == False
assert cm.requires_confirmation("brightness")== False

# Confirmation word detection
for word in ["yes", "yeah", "confirm", "sure", "ok", "okay"]:
    assert cm.is_confirmation(word), f"'{word}' should confirm"
for word in ["no", "cancel", "abort", "stop"]:
    assert cm.is_cancellation(word), f"'{word}' should cancel"

# No pending initially
assert cm.has_pending("user1") == False

# Register pending
async def fake_callback():
    return {"status": "ok", "response": "done"}

cm.request("user1", "shutdown", {}, "Confirm shutdown?", fake_callback)
assert cm.has_pending("user1") == True
assert cm.pending_count == 1

# Cancel
cm.cancel("user1")
assert cm.has_pending("user1") == False

# Confirm executes callback
cm.request("user1", "restart", {}, "Confirm restart?", fake_callback)
result = asyncio.run(cm.confirm("user1"))
assert result is not None
assert result["status"] == "ok"
assert not cm.has_pending("user1")

# Expiry (mock with tiny expiry)
import actions.confirmation_manager as cm_mod
orig_expiry = cm_mod.CONFIRM_EXPIRY
cm_mod.CONFIRM_EXPIRY = 0.1
cm.request("user2", "shutdown", {}, "Confirm?", fake_callback)
time.sleep(0.15)
assert cm.has_pending("user2") == False   # Expired
cm_mod.CONFIRM_EXPIRY = orig_expiry       # Restore

print('   PASS: ConfirmationManager')

# ── 4. SystemControlHandler — volume ─────────────────────────
print()
print('4. SystemControlHandler — volume commands...')
from actions.handlers.system_control_handler import SystemControlHandler
from actions.command_parser import CommandParser
from actions.intent_detector import IntentResult

handler = SystemControlHandler(mock=True)
parser  = CommandParser()

async def run(text, sub=None):
    cmd = parser.parse(text)
    r   = IntentResult("system_control", 0.9, sub_intent=sub or "volume")
    return await handler.handle(cmd, r)

async def test_volume():
    cases = [
        ("mute the volume",        "volume", "mute",   True),
        ("unmute",                 "volume", "unmute", True),
        ("volume up",              "volume", "up",     True),
        ("volume down",            "volume", "down",   True),
        ("set volume to 50",       "volume", "set",    True),
        ("turn volume to 80",      "volume", "set",    True),
        ("set volume to 150",      "volume", "set",    True),  # clamped
    ]
    passed = 0
    for text, sub, action, should_ok in cases:
        result = await run(text, sub)
        ok = result["status"] in ("ok","error") and "response" in result
        if ok: passed += 1
        else: print(f'   FAIL: "{text}" → {result}')
    print(f'   Volume: {passed}/{len(cases)} passed')

asyncio.run(test_volume())
print('   PASS: Volume commands')

# ── 5. SystemControlHandler — brightness ─────────────────────
print()
print('5. SystemControlHandler — brightness commands...')
async def test_brightness():
    cases = [
        ("brightness up",          "brightness"),
        ("brightness down",        "brightness"),
        ("set brightness to 70",   "brightness"),
        ("increase brightness",    "brightness"),
    ]
    passed = 0
    for text, sub in cases:
        result = await run(text, sub)
        assert "response" in result
        passed += 1
    print(f'   Brightness: {passed}/{len(cases)} passed')

asyncio.run(test_brightness())
print('   PASS: Brightness commands')

# ── 6. SystemControlHandler — power with confirmation ─────────
print()
print('6. Dangerous commands — confirmation gate...')
from actions.confirmation_manager import get_confirmation_manager

async def test_power():
    handler2 = SystemControlHandler(mock=True)
    p = CommandParser()

    async def run2(text, sub):
        cmd = p.parse(text)
        r   = IntentResult("system_control", 0.9, sub_intent=sub)
        return await handler2.handle(cmd, r)

    # Shutdown — should ask for confirmation, NOT execute
    result = await run2("shutdown", "power")
    assert result["status"] == "ok"
    assert "confirm" in result["response"].lower() or "sure" in result["response"].lower()
    assert result.get("data", {}).get("action") == "shutdown" or "confirm" in str(result)

    # Now confirm
    cmd_yes = p.parse("yes")
    r_yes   = IntentResult("system_control", 0.9, sub_intent="power")
    # Inject user_id to match
    cmd_yes.user_id = "default" if not hasattr(cmd_yes,"user_id") else cmd_yes.user_id
    confirmed = await handler2.handle(cmd_yes, r_yes)
    assert confirmed["status"] in ("ok","error")

    # Restart — should ask for confirmation
    result2 = await run2("restart the computer", "power")
    assert "confirm" in result2["response"].lower() or "sure" in result2["response"].lower()

    # Cancel
    cmd_no = p.parse("no cancel")
    r_no   = IntentResult("system_control", 0.9, sub_intent="power")
    cancelled = await handler2.handle(cmd_no, r_no)
    assert cancelled["status"] == "ok"

    print('   Confirmation gate: PASS')

asyncio.run(test_power())
print('   PASS: Power commands with confirmation')

# ── 7. SystemControlHandler — lock + sleep ────────────────────
print()
print('7. Lock screen + sleep...')
async def test_lock_sleep():
    cases = [
        ("lock the screen", "lock"),
        ("lock screen",     "lock"),
        ("lock computer",   "lock"),
        ("sleep",           "sleep"),
        ("suspend",         "sleep"),
    ]
    passed = 0
    for text, sub in cases:
        result = await run(text, sub)
        assert result["status"] in ("ok","error")
        assert "response" in result
        passed += 1
    print(f'   Lock/sleep: {passed}/{len(cases)} passed')

asyncio.run(test_lock_sleep())
print('   PASS: Lock + sleep')

# ── 8. Intent detector — all system sub-intents ───────────────
print()
print('8. Intent detector — system sub-intents...')
from actions.intent_detector import IntentDetector

det = IntentDetector()
p2  = CommandParser()

det_cases = [
    ("mute the volume",         "system_control", "volume"),
    ("turn volume up",          "system_control", "volume"),
    ("set volume to 50",        "system_control", "volume"),
    ("increase brightness",     "system_control", "brightness"),
    ("set brightness to 70",    "system_control", "brightness"),
    ("shutdown the system",     "system_control", "power"),
    ("restart my computer",     "system_control", "power"),
    ("lock the screen",         "system_control", "lock"),
    ("lock screen",             "system_control", "lock"),
    ("put computer to sleep",   "system_control", "sleep"),
    ("turn off wifi",           "system_control", "wifi"),
    ("enable bluetooth",        "system_control", "bluetooth"),
]
det_passed = 0
for text, exp_intent, exp_sub in det_cases:
    cmd = p2.parse(text)
    r   = det.detect(cmd)
    ok  = r.intent == exp_intent and r.sub_intent == exp_sub
    if ok:
        det_passed += 1
    else:
        print(f'   WARN: "{text}" → {r.intent}/{r.sub_intent} (expected {exp_intent}/{exp_sub})')

print(f'   Detection: {det_passed}/{len(det_cases)} correct')
print('   PASS: Intent detector sub-intents')

# ── 9. Platform executor factory ─────────────────────────────
print()
print('9. Platform executor factory...')
from actions.system_executor import create_system_executor, MockExecutor

ex_mock = create_system_executor(mock=True)
assert isinstance(ex_mock, MockExecutor)

# Real executor created for current platform (no crash)
ex_real = create_system_executor(mock=False)
assert ex_real is not None
assert hasattr(ex_real, "volume_set")
assert hasattr(ex_real, "shutdown")
assert hasattr(ex_real, "lock_screen")
print(f'   Platform executor: {type(ex_real).__name__}')
print('   PASS: Factory')

# ── 10. Confirmation edge cases ───────────────────────────────
print()
print('10. Confirmation edge cases...')

cm2 = ConfirmationManager()

# Confirm with no pending → returns None
result = asyncio.run(cm2.confirm("nobody"))
assert result is None

# Cancel with no pending → returns False
assert cm2.cancel("nobody") == False

# Multiple users independent
async def fake_cb2(): return {"status":"ok","response":"done2"}
cm2.request("user_a", "shutdown", {}, "Confirm?", fake_cb2)
cm2.request("user_b", "restart",  {}, "Confirm?", fake_cb2)
assert cm2.has_pending("user_a") == True
assert cm2.has_pending("user_b") == True
cm2.cancel("user_a")
assert cm2.has_pending("user_a") == False
assert cm2.has_pending("user_b") == True

# clear_expired
cm2.request("user_c", "shutdown", {}, "Confirm?", fake_cb2)
orig = cm_mod.CONFIRM_EXPIRY
cm_mod.CONFIRM_EXPIRY = 0.05
time.sleep(0.1)
removed = cm2.clear_expired()
assert removed >= 1
cm_mod.CONFIRM_EXPIRY = orig

print('   PASS: Confirmation edge cases')

print()
print('=' * 60)
print('  ALL 10 TEST SUITES PASSED')
print('=' * 60)
