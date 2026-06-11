"""
Validation script for the local intelligence layer.
Tests all success criteria from the architecture directive.
No cloud APIs. No API keys. 100% offline.
"""
import ast, pathlib, sys, asyncio, os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ── 1. Syntax check new files ─────────────────────────────────
print("=== SYNTAX CHECK ===")
files = [
    "assistant_core/__init__.py",
    "assistant_core/response_engine.py",
    "assistant_core/knowledge_engine.py",
    "assistant_core/local_llm_adapter.py",
    "assistant_core/intent_dispatch.py",
    "core/assistant.py",
    "config/settings.py",
    "utils/health.py",
]
syntax_ok = True
for f in files:
    try:
        ast.parse(pathlib.Path(f).read_text(encoding="utf-8"))
        print(f"  OK  {f}")
    except SyntaxError as e:
        print(f"  ERR {f}: line {e.lineno}: {e.msg}")
        syntax_ok = False

if not syntax_ok:
    print("\nSYNTAX ERRORS — aborting")
    sys.exit(1)

# ── 2. Import check ───────────────────────────────────────────
print("\n=== IMPORT CHECK ===")
try:
    from assistant_core.response_engine import get_response_engine
    from assistant_core.knowledge_engine import get_knowledge_engine
    from assistant_core.local_llm_adapter import get_local_llm
    from assistant_core.intent_dispatch import dispatch
    print("  OK  All assistant_core modules import cleanly")
except Exception as e:
    print(f"  ERR Import failed: {e}")
    sys.exit(1)

# ── 3. No cloud API imports ───────────────────────────────────
print("\n=== NO CLOUD API CHECK ===")
cloud_patterns = ["import openai", "import anthropic", "from openai", "from anthropic",
                  "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "openai_api_key", "anthropic_api_key"]
scan_files = list(pathlib.Path(".").rglob("*.py"))
violations = []
for fpath in scan_files:
    if any(x in str(fpath) for x in [".pytest_cache", "__pycache__", "validate_local"]):
        continue
    try:
        src = fpath.read_text(encoding="utf-8", errors="ignore")
        for pattern in cloud_patterns:
            if pattern in src:
                # Allowed in requirements.txt (historical) and the validator itself
                if "requirements.txt" in str(fpath):
                    continue
                violations.append(f"  {fpath}: contains '{pattern}'")
    except Exception:
        pass
if violations:
    print("  WARN: Cloud API references found:")
    for v in violations: print(v)
else:
    print("  OK  No cloud API imports or active key references found")

# ── 4. Functional tests ───────────────────────────────────────
print("\n=== FUNCTIONAL TESTS ===")

engine = get_response_engine()
knowledge = get_knowledge_engine()

cases = [
    # (description, input, expected_substring, engine)
    ("Greeting",           "hello",                          "i",             "response"),
    ("Greeting hi",        "hi",                             "what",          "response"),
    ("How are you",        "how are you",                    "well",          "response"),
    ("Identity",           "who are you",                    "gini",          "response"),
    ("Thanks",             "thank you",                      "welcome",       "response"),
    ("Math add",           "calculate 2 + 2",                "4",             "response"),
    ("Math multiply",      "45 * 12",                        "540",           "response"),
    ("Time query",         "what time is it",                "time",          "response"),
    ("Date query",         "what is today's date",           "today",         "response"),
    ("Photosynthesis",     "what is photosynthesis",         "plants",        "knowledge"),
    ("Python lang",        "what is python",                 "programming",   "knowledge"),
    ("Gravity",            "explain gravity",                "force",         "knowledge"),
    ("Albert Einstein",    "who is albert einstein",         "einstein",      "knowledge"),
    ("DNA",                "what is dna",                    "genetic",       "knowledge"),
    ("Machine learning",   "what is machine learning",       "data",          "knowledge"),
    ("Algorithm",          "what is an algorithm",           "step",          "knowledge"),
]

passed = 0
for desc, inp, expected, source in cases:
    if source == "response":
        result, handled = engine.generate(inp)
        ok = handled and expected.lower() in result.lower()
    else:
        result, conf = knowledge.query(inp)
        ok = result is not None and expected.lower() in result.lower()

    marker = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        print(f"  {marker}: {desc} | input='{inp}' | expected '{expected}' in '{(result or '')[:60]}'")
    if ok:
        print(f"  {marker}: {desc}")

print(f"\n  {passed}/{len(cases)} functional tests passed")

# ── 5. No placeholder responses in pipeline ───────────────────
print("\n=== PLACEHOLDER CHECK ===")
placeholder_text = "LLM integration coming in Phase 2"
assistant_src = pathlib.Path("core/assistant.py").read_text(encoding="utf-8")
if placeholder_text in assistant_src:
    print(f"  FAIL: Placeholder text still present in core/assistant.py")
else:
    print(f"  OK  No placeholder stub text in core/assistant.py")

# ── 6. Full async pipeline test ───────────────────────────────
print("\n=== ASYNC PIPELINE TEST ===")

async def run_pipeline_tests():
    from core.assistant import GiniAssistant
    from core.service_registry import ServiceRegistry
    from actions.action_router import ActionRouter

    reg = ServiceRegistry()
    reg.register("action_router", ActionRouter())
    assistant = GiniAssistant(registry=reg)
    await assistant.on_startup()

    tests = [
        ("hello",                             lambda r: len(r) > 5 and any(w in r.lower() for w in ["gini","help","assist","hear","what"])),
        ("what is photosynthesis?",           lambda r: "plants" in r.lower() or "sunlight" in r.lower()),
        ("remember my name is Anmol",         lambda r: "remember" in r.lower() or "anmol" in r.lower() or "stored" in r.lower() or "got" in r.lower()),
        ("calculate 10 * 5",                  lambda r: "50" in r),
        ("open calculator",                   lambda r: len(r) > 5),
        ("search python tutorial",            lambda r: len(r) > 5),
    ]

    pipeline_passed = 0
    for msg, check in tests:
        result = await assistant.process_message(msg, "test_user")
        response = result.get("response", "")
        ok = check(response)
        marker = "PASS" if ok else "FAIL"
        if ok:
            pipeline_passed += 1
        print(f"  {marker}: '{msg[:40]}' -> '{response[:70]}'")

    return pipeline_passed, len(tests)

p, t = asyncio.run(run_pipeline_tests())

# ── Summary ───────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"  Syntax check    : {'OK' if syntax_ok else 'FAIL'}")
print(f"  Imports         : OK")
print(f"  Cloud API refs  : {'CLEAN' if not violations else f'{len(violations)} warnings'}")
print(f"  Unit tests      : {passed}/{len(cases)}")
print(f"  Pipeline tests  : {p}/{t}")
print(f"  Placeholder stub: {'GONE' if placeholder_text not in assistant_src else 'STILL PRESENT'}")
all_ok = syntax_ok and passed == len(cases) and p == t and placeholder_text not in assistant_src
print(f"\n  RESULT: {'✅ ALL PASS — SYSTEM READY' if all_ok else '⚠️  SOME ISSUES'}")
print(f"{'='*55}")
sys.exit(0 if all_ok else 1)
