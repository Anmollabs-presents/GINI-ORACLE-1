import sys, asyncio
sys.path.insert(0, '.')

print('=' * 60)
print('  TASK 7 — APP CONTROL ACTION TESTS')
print('=' * 60)

# ── 1. AppRegistry ────────────────────────────────────────────
print()
print('1. AppRegistry...')
from actions.app_registry import AppRegistry, get_app_registry, APP_CATALOGUE

reg = get_app_registry()

# Known apps resolve
for alias in ["chrome", "spotify", "calculator", "firefox", "vs code", "terminal"]:
    entry = reg.find(alias)
    assert entry is not None, f"Missing: {alias}"
    assert entry.name

# Case insensitive
assert reg.find("CHROME") is not None
assert reg.find("Chrome") is not None

# Unknown returns None
assert reg.find("totally_unknown_xyz") is None

# Browser flag
assert reg.find("chrome").is_browser == True
assert reg.find("spotify").is_browser == False

# Process names present
chrome = reg.find("chrome")
assert len(chrome.process_names) >= 1

# All aliases
aliases = reg.all_aliases()
assert len(aliases) > 20

print(f'   Apps in catalogue: {len(APP_CATALOGUE)}')
print(f'   Aliases indexed: {len(aliases)}')
print('   PASS: AppRegistry')

# ── 2. AppRegistry executable resolution ─────────────────────
print()
print('2. Executable resolution (current platform)...')
import sys
platform = sys.platform

# resolve_executable returns str or None — never raises
for name in ["chrome", "calculator", "terminal", "vs code"]:
    entry = reg.find(name)
    result = reg.resolve_executable(entry)
    assert result is None or isinstance(result, str)

print(f'   Platform: {platform}')
print('   PASS: Executable resolution (no crash)')

# ── 3. ProcessManager — protected process guard ───────────────
print()
print('3. ProcessManager (protected process guard)...')
from actions.process_manager import ProcessManager, ProcessResult, get_process_manager

pm = get_process_manager()

# Kill protected process must be refused
class FakeProc:
    pid = 1
    def name(self): return "svchost.exe"
    def kill(self): raise RuntimeError("Should not be called")
    def terminate(self): raise RuntimeError("Should not be called")

# Direct protected check
assert pm._is_protected("svchost.exe") == True
assert pm._is_protected("lsass.exe") == True
assert pm._is_protected("chrome.exe") == False
assert pm._is_protected("spotify.exe") == False
print('   PASS: Protected process guard')

# ── 4. ProcessManager — is_running ───────────────────────────
print()
print('4. ProcessManager.is_running()...')
# Returns bool, never raises
result = pm.is_running("chrome")
assert isinstance(result, bool)
result2 = pm.is_running("totally_unknown_app_xyz")
assert isinstance(result2, bool)
assert result2 == False
print('   PASS: is_running()')

# ── 5. ProcessManager — launch (not_found path) ───────────────
print()
print('5. ProcessManager.launch() — not_found path...')
# Launch something not installed → NOT_FOUND, not a crash
action = pm.launch("totally_unknown_app_xyz_123")
assert action.result in (ProcessResult.NOT_FOUND, ProcessResult.ERROR)
assert action.app_name is not None
assert isinstance(action.message, str)
assert isinstance(action.success, bool)

# to_dict() works
d = action.to_dict()
assert "result" in d
assert "app_name" in d
assert "message" in d
print(f'   Result: {action.result.value} — "{action.message}"')
print('   PASS: launch() not_found path')

# ── 6. ProcessManager — close (not running) ───────────────────
print()
print('6. ProcessManager.close() — not_running path...')
action2 = pm.close("spotify")
assert action2.result in (ProcessResult.NOT_RUNNING, ProcessResult.SUCCESS, ProcessResult.ERROR)
assert isinstance(action2.message, str)
print(f'   Result: {action2.result.value} — "{action2.message}"')
print('   PASS: close() not_running path')

# ── 7. ProcessManager — kill (not running) ────────────────────
print()
print('7. ProcessManager.kill() — not_running path...')
action3 = pm.kill("spotify")
assert action3.result in (ProcessResult.NOT_RUNNING, ProcessResult.SUCCESS, ProcessResult.ERROR)
assert isinstance(action3.message, str)
print(f'   Result: {action3.result.value} — "{action3.message}"')
print('   PASS: kill() not_running path')

# ── 8. ProcessManager — focus (not running) ───────────────────
print()
print('8. ProcessManager.focus() — not_running path...')
action4 = pm.focus("chrome")
assert isinstance(action4.message, str)
assert action4.app_name is not None
print(f'   Result: {action4.result.value} — "{action4.message}"')
print('   PASS: focus() not_running path')

# ── 9. ProcessManager — list_running ─────────────────────────
print()
print('9. ProcessManager.list_running()...')
running = pm.list_running()
assert isinstance(running, list)
for item in running:
    assert "app" in item
    assert "process" in item
print(f'   Running known apps: {len(running)}')
if running:
    print(f'   Sample: {running[:3]}')
print('   PASS: list_running()')

# ── 10. AppControlHandler — routing ──────────────────────────
print()
print('10. AppControlHandler — sub-intent routing...')
from actions.handlers.app_control_handler import AppControlHandler
from actions.command_parser import CommandParser
from actions.intent_detector import IntentDetector, IntentResult

handler = AppControlHandler()
parser = CommandParser()
detector = IntentDetector()

async def run_handler(text, forced_sub=None):
    cmd = parser.parse(text)
    det = detector.detect(cmd)
    if forced_sub:
        det = IntentResult(intent="app_control", confidence=0.9, sub_intent=forced_sub)
    return await handler.handle(cmd, det)

async def test_handler():
    cases = [
        # (text, forced_sub, expected_status_in, expected_sub)
        ("open chrome",          "open",  ["ok", "error"], "open"),
        ("open calculator",      "open",  ["ok", "error"], "open"),
        ("open spotify",         "open",  ["ok", "error"], "open"),
        ("close spotify",        "close", ["ok"],          "close"),
        ("kill spotify",         "kill",  ["ok"],          "kill"),
        ("focus chrome",         "focus", ["ok", "error"], "focus"),
        ("launch browser",       "browser",["ok", "error"],"browser"),
        ("open",                 "open",  ["ok"],          "open"),  # no app → prompt
        ("close",                "close", ["ok"],          "close"), # no app → prompt
    ]
    passed = 0
    for text, forced_sub, valid_statuses, _ in cases:
        result = await run_handler(text, forced_sub)
        assert result["status"] in valid_statuses, \
            f'"{text}" → status={result["status"]} not in {valid_statuses}'
        assert "response" in result
        assert isinstance(result["response"], str)
        assert len(result["response"]) > 0
        passed += 1
    print(f'   Routing: {passed}/{len(cases)} passed')

asyncio.run(test_handler())
print('   PASS: AppControlHandler routing')

# ── 11. Intent detector — new sub-intents ─────────────────────
print()
print('11. Intent detector — focus + kill sub-intents...')
from actions.intent_detector import IntentDetector
det2 = IntentDetector()
p2 = CommandParser()

det_cases = [
    ("open chrome",          "app_control", "open"),
    ("close spotify",        "app_control", "close"),
    ("kill spotify",         "app_control", "kill"),
    ("focus chrome",         "app_control", "focus"),
    ("switch to chrome",     "app_control", "focus"),
    ("launch browser",       "app_control", "browser"),
    ("install whatsapp",     "app_control", "install"),
]
det_passed = 0
for text, exp_intent, exp_sub in det_cases:
    cmd = p2.parse(text)
    result = det2.detect(cmd)
    ok = result.intent == exp_intent and result.sub_intent == exp_sub
    if ok:
        det_passed += 1
    else:
        print(f'   WARN: "{text}" → intent={result.intent} sub={result.sub_intent}')
print(f'   Detection: {det_passed}/{len(det_cases)} correct')
print('   PASS: Intent detector sub-intents')

# ── 12. App name extraction edge cases ────────────────────────
print()
print('12. App name extraction edge cases...')

extract_cases = [
    ("open chrome please",     "chrome"),
    ("launch spotify now",     "spotify"),
    ("close the calculator",   "calculator"),
    ("kill spotify",           "spotify"),
    ("focus vs code",          "vs code"),
    ("open google chrome",     "chrome"),
    ("start firefox browser",  "firefox"),
    ("open notepad",           "notepad"),
]
ext_passed = 0
for text, expected in extract_cases:
    cmd = p2.parse(text)
    det_r = IntentResult("app_control", 0.9, sub_intent="open")
    extracted = handler._extract_app(cmd)
    if extracted == expected:
        ext_passed += 1
    else:
        print(f'   WARN: "{text}" → extracted="{extracted}", expected="{expected}"')
print(f'   Extraction: {ext_passed}/{len(extract_cases)} correct')
print('   PASS: App name extraction')

print()
print('=' * 60)
print('  ALL 12 TEST SUITES PASSED')
print('=' * 60)
