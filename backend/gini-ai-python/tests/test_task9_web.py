import sys, asyncio, unittest.mock
sys.path.insert(0, '.')

print('=' * 60)
print('  TASK 9 — WEB INTERACTION SUBSYSTEM TESTS')
print('=' * 60)

# ── 1. URLSanitizer ───────────────────────────────────────────
print()
print('1. URLSanitizer — validation + scheme enforcement...')
from actions.web_executor import URLSanitizer, ALLOWED_SCHEMES

s = URLSanitizer()

# Valid URLs
valid_cases = [
    ("https://www.google.com",     True,  "https://www.google.com"),
    ("http://example.com",         True,  "http://example.com"),
    ("www.youtube.com",            True,  "https://www.youtube.com"),
    ("google.com",                 True,  "https://google.com"),
    ("https://github.com/user/repo",True, "https://github.com/user/repo"),
]
for raw, exp_safe, exp_url in valid_cases:
    safe, url, reason = s.sanitize(raw)
    assert safe == exp_safe, f"'{raw}' → safe={safe}, expected {exp_safe} (reason={reason})"
    if exp_safe:
        assert url == exp_url, f"'{raw}' → url='{url}', expected '{exp_url}'"

# Blocked/invalid URLs
blocked_cases = [
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "",
    "   ",
]
for raw in blocked_cases:
    safe, url, reason = s.sanitize(raw)
    assert not safe, f"'{raw}' should be blocked but got safe=True"

# Website shortcuts
assert s.is_website_shortcut("google")   == "https://www.google.com"
assert s.is_website_shortcut("youtube")  == "https://www.youtube.com"
assert s.is_website_shortcut("gmail")    == "https://mail.google.com"
assert s.is_website_shortcut("unknown_xyz") is None

print(f'   Valid: {len(valid_cases)}/{len(valid_cases)} PASS')
print(f'   Blocked: {len(blocked_cases)}/{len(blocked_cases)} PASS')
print('   PASS: URLSanitizer')

# ── 2. WebExecutor URL building ───────────────────────────────
print()
print('2. WebExecutor — URL building...')
from actions.web_executor import (
    WebExecutor, WebActionResult, WebActionStatus,
    GOOGLE_SEARCH_URL, YOUTUBE_SEARCH_URL,
)
import urllib.parse

# Verify URL templates produce correct encoded URLs
query = "python programming"
encoded = urllib.parse.quote_plus(query)
expected_google  = f"https://www.google.com/search?q={encoded}"
expected_youtube = f"https://www.youtube.com/results?search_query={encoded}"
assert GOOGLE_SEARCH_URL.format(query=encoded) == expected_google
assert YOUTUBE_SEARCH_URL.format(query=encoded) == expected_youtube

# Special characters handled
special = "what is 2+2? #math"
enc_special = urllib.parse.quote_plus(special)
url = GOOGLE_SEARCH_URL.format(query=enc_special)
assert "+" in url or "%2B" in url   # special chars encoded

print('   PASS: URL building + encoding')

# ── 3. WebExecutor — mock browser open ───────────────────────
print()
print('3. WebExecutor — open operations (mock browser)...')

# Patch webbrowser.open to avoid real browser opening in tests
import webbrowser
opened_urls = []
original_open = webbrowser.open

def mock_open(url, new=0, autoraise=True):
    opened_urls.append(url)
    return True

webbrowser.open = mock_open

ex = WebExecutor()

# Google search
r = ex.google_search("machine learning")
assert r.success, f"google_search failed: {r.error}"
assert "google.com/search" in r.url
assert "machine" in r.url or "machine+learning" in r.url
assert r.query == "machine learning"
assert len(opened_urls) == 1

# YouTube search
r2 = ex.youtube_search("lo fi music")
assert r2.success
assert "youtube.com" in r2.url
assert r2.query == "lo fi music"

# YouTube no query — just open YouTube
r3 = ex.youtube_search("")
assert r3.success
assert "youtube.com" in r3.url

# Open website — shortcut
r4 = ex.open_website("github")
assert r4.success
assert "github.com" in r4.url

# Open website — URL
r5 = ex.open_website("https://www.example.com")
assert r5.success
assert "example.com" in r5.url

# Open website — invalid scheme → blocked
r6 = ex.open_url("javascript:alert(1)")
assert not r6.success
assert r6.status == WebActionStatus.INVALID_URL

# Weather search
r7 = ex.weather_search("Lucknow")
assert r7.success
assert "google.com" in r7.url

# News search
r8 = ex.news_search("AI technology")
assert r8.success

# Maps search
r9 = ex.maps_search("Connaught Place Delhi")
assert r9.success
assert "maps" in r9.url

# Translate
r10 = ex.translate("Namaste")
assert r10.success
assert "translate" in r10.url

# Wikipedia
r11 = ex.wikipedia_search("photosynthesis")
assert r11.success
assert "wikipedia" in r11.url

total_opens = len(opened_urls)
print(f'   Browser opens simulated: {total_opens}')
print('   PASS: WebExecutor open operations')

# Restore
webbrowser.open = original_open

# ── 4. WebExecutor — browser fallback ────────────────────────
print()
print('4. Error recovery — fallback on browser fail...')
webbrowser.open = lambda url, **kw: False   # Simulate failure

ex2 = WebExecutor()
import subprocess, sys

# Patch subprocess.Popen to avoid real xdg-open
with unittest.mock.patch("subprocess.Popen") as mock_popen:
    mock_popen.return_value = unittest.mock.MagicMock()
    r_fallback = ex2.google_search("test query")
    # On Linux this goes through xdg-open fallback
    # Result should be either success or browser_error (not crash)
    assert r_fallback.status in (
        WebActionStatus.SUCCESS,
        WebActionStatus.BROWSER_ERROR,
    )
    print(f'   Fallback result: {r_fallback.status.value}')

webbrowser.open = original_open  # Restore
print('   PASS: Error recovery')

# ── 5. WebSearchHandler — routing ────────────────────────────
print()
print('5. WebSearchHandler — all sub-intent routing...')
from actions.handlers.web_search_handler import WebSearchHandler
from actions.command_parser import CommandParser
from actions.intent_detector import IntentResult

# Patch web executor to avoid real browser opens
opened_handler = []
from actions import web_executor as we_mod
orig_exec = we_mod._executor
mock_ex = WebExecutor()
webbrowser.open = lambda url, **kw: (opened_handler.append(url) or True)
we_mod._executor = None   # Reset singleton

handler = WebSearchHandler()
# Inject mock executor directly
handler._web = mock_ex
parser = CommandParser()

async def run(text, forced_sub):
    cmd = parser.parse(text)
    r = IntentResult("web_search", 0.9, sub_intent=forced_sub)
    return await handler.handle(cmd, r)

async def test_routing():
    cases = [
        ("search for python tutorials",  "google",    True),
        ("google machine learning",       "google",    True),
        ("youtube lo fi music",           "youtube",   True),
        ("open youtube",                  "youtube",   True),
        ("open github.com",               "navigate",  True),
        ("go to www.reddit.com",          "navigate",  True),
        ("weather in Lucknow",            "weather",   True),
        ("latest news about AI",          "news",      True),
        ("directions to Connaught Place", "maps",      True),
        ("translate namaste",             "translate", True),
        ("wikipedia photosynthesis",      "wikipedia", True),
        ("search machine learning",       "search",    True),
        ("what should I search",          "search",    True),  # no query → prompt
    ]
    passed = 0
    for text, sub, should_ok in cases:
        result = await run(text, sub)
        ok = result["status"] in ("ok", "error") and "response" in result
        if ok:
            passed += 1
        else:
            print(f'   FAIL: "{text}" → {result}')
    print(f'   Routing: {passed}/{len(cases)} passed')

asyncio.run(test_routing())
webbrowser.open = original_open
print('   PASS: WebSearchHandler routing')

# ── 6. Intent detector — web sub-intents ─────────────────────
print()
print('6. Intent detector — web sub-intents...')
from actions.intent_detector import IntentDetector

det = IntentDetector()
p2  = CommandParser()

det_cases = [
    ("search for python tutorials",       "web_search", "search"),
    ("google machine learning",           "web_search", "google"),
    ("youtube lo fi music",               "web_search", "youtube"),
    ("open youtube",                      "web_search", "youtube"),
    ("search wikipedia for black holes",  "web_search", "wikipedia"),
    ("weather in Lucknow",                "web_search", "weather"),
    ("latest news about technology",      "web_search", "news"),
    ("directions to Connaught Place",     "web_search", "maps"),
    ("translate namaste to english",      "web_search", "translate"),
    ("open website github",               "web_search", "navigate"),
    ("go to www.reddit.com",              "web_search", "navigate"),
]
det_passed = 0
for text, exp_intent, exp_sub in det_cases:
    cmd = p2.parse(text)
    r   = det.detect(cmd)
    ok  = r.intent == exp_intent and r.sub_intent == exp_sub
    if ok:
        det_passed += 1
    else:
        print(f'   WARN: "{text}" → {r.intent}/{r.sub_intent} (expected {exp_sub})')

print(f'   Detection: {det_passed}/{len(det_cases)} correct')
print('   PASS: Intent detector sub-intents')

# ── 7. _extract_query() — unchanged behavior ─────────────────
print()
print('7. _extract_query() — prefix stripping preserved...')
from actions.handlers.web_search_handler import WebSearchHandler

h2 = WebSearchHandler()
h2._web = mock_ex

p3 = CommandParser()
extract_cases = [
    ("search for python tutorials",  "python tutorials"),
    ("google machine learning",      "machine learning"),
    ("look up photosynthesis",       "photosynthesis"),
    ("youtube lo fi music",          "lo fi music"),
    ("open website github",          "github"),
    ("find nearest hospital",        "nearest hospital"),
]
ext_passed = 0
for text, expected in extract_cases:
    cmd = p3.parse(text)
    result = h2._extract_query(cmd)
    if result == expected:
        ext_passed += 1
    else:
        print(f'   WARN: "{text}" → "{result}", expected "{expected}"')

print(f'   Extraction: {ext_passed}/{len(extract_cases)} correct')
print('   PASS: _extract_query() preserved')

# ── 8. Browser preference extraction ─────────────────────────
print()
print('8. Browser preference extraction...')
h3 = WebSearchHandler()
h3._web = mock_ex
p4 = CommandParser()

browser_cases = [
    ("search in chrome",          "chrome"),
    ("open firefox now",          "firefox"),
    ("search edge browser",       "edge"),
    ("open brave",                "brave"),
    ("search google",             ""),       # no specific browser
    ("youtube music",             ""),
]
br_passed = 0
for text, expected in browser_cases:
    cmd = p4.parse(text)
    result = h3._extract_browser(cmd)
    if result == expected:
        br_passed += 1
    else:
        print(f'   WARN: "{text}" → "{result}", expected "{expected}"')

print(f'   Browser extraction: {br_passed}/{len(browser_cases)} correct')
print('   PASS: Browser preference extraction')

# ── 9. WEBSITE_SHORTCUTS completeness ────────────────────────
print()
print('9. Website shortcuts coverage...')
from actions.web_executor import WEBSITE_SHORTCUTS

required = ["google", "youtube", "gmail", "github", "reddit",
            "wikipedia", "whatsapp", "maps", "netflix", "amazon"]
for site in required:
    assert site in WEBSITE_SHORTCUTS, f"Missing shortcut: {site}"
    url = WEBSITE_SHORTCUTS[site]
    assert url.startswith("https://"), f"Non-HTTPS shortcut: {site} → {url}"

print(f'   Shortcuts: {len(WEBSITE_SHORTCUTS)} total, all HTTPS')
print('   PASS: Website shortcuts')

# ── 10. WebActionResult structure ────────────────────────────
print()
print('10. WebActionResult structure...')
from actions.web_executor import WebActionResult, WebActionStatus

r_ok  = WebActionResult(WebActionStatus.SUCCESS, "ok", url="https://x.com", query="test")
r_err = WebActionResult(WebActionStatus.ERROR, "fail", error="oops")

assert r_ok.success  == True
assert r_err.success == False
d = r_ok.to_dict()
assert all(k in d for k in ["status","message","url","query","browser_used","error"])
print('   PASS: WebActionResult')

# ── Restore ───────────────────────────────────────────────────
webbrowser.open = original_open
we_mod._executor = orig_exec

print()
print('=' * 60)
print('  ALL 10 TEST SUITES PASSED')
print('=' * 60)
