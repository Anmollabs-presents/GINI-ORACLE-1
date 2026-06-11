# ============================================================
# GINI-ORACLE-1 — Execution Engine Tests
# tests/test_engine.py
# ============================================================

import pytest
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Service Registry ──────────────────────────────────────────

def test_service_registry_register_and_resolve():
    from core.service_registry import ServiceRegistry
    reg = ServiceRegistry()
    reg.register("my_service", {"value": 42})
    result = reg.resolve("my_service")
    assert result == {"value": 42}


def test_service_registry_raises_on_missing():
    from core.service_registry import ServiceRegistry, ServiceNotFoundError
    reg = ServiceRegistry()
    with pytest.raises(ServiceNotFoundError):
        reg.resolve("nonexistent")


def test_service_registry_resolve_optional_returns_none():
    from core.service_registry import ServiceRegistry
    reg = ServiceRegistry()
    result = reg.resolve_optional("nonexistent")
    assert result is None


def test_service_registry_lazy_factory():
    from core.service_registry import ServiceRegistry
    reg = ServiceRegistry()
    called = {"count": 0}

    def factory():
        called["count"] += 1
        return "lazy_value"

    reg.register_factory("lazy", factory)
    assert called["count"] == 0       # Not called yet
    val = reg.resolve("lazy")
    assert val == "lazy_value"
    assert called["count"] == 1       # Called on resolve
    reg.resolve("lazy")               # Second call uses cache
    assert called["count"] == 1       # Factory not called again


def test_service_registry_has():
    from core.service_registry import ServiceRegistry
    reg = ServiceRegistry()
    reg.register("svc", object())
    assert reg.has("svc") is True
    assert reg.has("missing") is False


def test_service_registry_no_overwrite_by_default():
    from core.service_registry import ServiceRegistry
    reg = ServiceRegistry()
    reg.register("svc", "first")
    reg.register("svc", "second")            # Should be ignored
    assert reg.resolve("svc") == "first"


def test_service_registry_overwrite():
    from core.service_registry import ServiceRegistry
    reg = ServiceRegistry()
    reg.register("svc", "first")
    reg.register("svc", "second", overwrite=True)
    assert reg.resolve("svc") == "second"


# ── Memory Manager ────────────────────────────────────────────

def test_memory_creates_session():
    from core.memory import MemoryManager
    mm = MemoryManager(database_url="sqlite:///:memory:")
    session = mm.get_or_create_session("user_1", "sess_1")
    assert session.user_id == "user_1"
    assert session.session_id == "sess_1"


def test_memory_get_same_session():
    from core.memory import MemoryManager
    mm = MemoryManager(database_url="sqlite:///:memory:")
    s1 = mm.get_or_create_session("user_1", "sess_abc")
    s2 = mm.get_or_create_session("user_1", "sess_abc")
    assert s1 is s2


def test_memory_add_and_get_history():
    from core.memory import MemoryManager
    mm = MemoryManager(database_url="sqlite:///:memory:")
    mm.get_or_create_session("user_1", "sess_1")
    mm.add_turn("sess_1", "user", "Hello Gini", emotion="positive")
    mm.add_turn("sess_1", "assistant", "Hi there!", emotion="positive")
    history = mm.get_history("sess_1")
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"


def test_memory_emotion_trend():
    from core.memory import MemoryManager
    mm = MemoryManager(database_url="sqlite:///:memory:")
    mm.get_or_create_session("u1", "s1")
    for _ in range(4):
        mm.add_turn("s1", "user", "I am sad", emotion="negative")
    mm.add_turn("s1", "user", "ok", emotion="neutral")
    trend = mm.get_emotion_trend("s1")
    assert trend == "negative"


def test_memory_clear_session():
    from core.memory import MemoryManager
    mm = MemoryManager(database_url="sqlite:///:memory:")
    mm.get_or_create_session("u1", "s1")
    mm.add_turn("s1", "user", "test", emotion="neutral")
    mm.clear_session("s1")
    assert mm.get_history("s1") == []


def test_memory_window_size():
    from core.memory import MemoryManager
    mm = MemoryManager(window_size=3, database_url="sqlite:///:memory:")
    mm.get_or_create_session("u1", "s1")
    for i in range(10):
        mm.add_turn("s1", "user", f"msg {i}", emotion="neutral")
    history = mm.get_history("s1")
    assert len(history) == 3
    assert history[-1]["content"] == "msg 9"


def test_memory_fact_store_and_recall():
    from core.memory import MemoryManager
    mm = MemoryManager(database_url="sqlite:///:memory:")
    mm.remember_fact("user_1", "name", "Anmol")
    mm.remember_fact("user_1", "preference", "dark mode")

    assert mm.recall_fact("user_1", "name") == "Anmol"
    facts = mm.recall_fact("user_1")
    assert isinstance(facts, dict)
    assert facts["name"] == "Anmol"
    assert facts["preference"] == "dark mode"


def test_wake_word_detector_text_match():
    from voice.wake_word_detector import WakeWordDetector, WakeWordConfig

    config = WakeWordConfig.for_testing()
    detector = WakeWordDetector(config=config)

    assert detector.is_wake("hey gini") is True
    assert detector.is_wake("hello gini") is True
    assert detector.is_wake("what time is it") is False


@pytest.mark.asyncio
async def test_memory_handler_name_recall():
    from actions.handlers.memory_handler import MemoryHandler
    from actions.command_parser import ParsedCommand
    from actions.intent_detector import IntentResult, INTENT_MEMORY
    from core.memory import MemoryManager
    from core.service_registry import get_registry

    registry = get_registry()
    registry.register("memory", MemoryManager(database_url="sqlite:///:memory:"), overwrite=True)

    handler = MemoryHandler()
    store_cmd = ParsedCommand(
        raw="my name is Anmol",
        normalized="my name is anmol",
        tokens=["my", "name", "is", "anmol"],
    )
    await handler.handle(store_cmd, IntentResult(INTENT_MEMORY, 0.9, ["remember"], sub_intent="store"))

    recall_cmd = ParsedCommand(
        raw="what is my name",
        normalized="what is my name",
        tokens=["what", "is", "my", "name"],
        is_question=True,
    )
    recall_result = await handler.handle(recall_cmd, IntentResult(INTENT_MEMORY, 0.9, ["know"], sub_intent="recall"))
    assert recall_result["status"] == "ok"
    assert "Your name is" in recall_result["response"]
    assert "Anmol" in recall_result["response"]

    registry.unregister("memory")


def test_memory_fact_forget():
    from core.memory import MemoryManager
    mm = MemoryManager(database_url="sqlite:///:memory:")
    mm.remember_fact("user_1", "name", "Anmol")
    deleted = mm.forget_fact("user_1", "name")
    assert deleted == 1
    assert mm.recall_fact("user_1", "name") is None


@pytest.mark.asyncio
async def test_memory_handler_store_recall_forget():
    from actions.handlers.memory_handler import MemoryHandler
    from actions.command_parser import ParsedCommand
    from actions.intent_detector import IntentResult, INTENT_MEMORY
    from core.memory import MemoryManager
    from core.service_registry import get_registry

    registry = get_registry()
    registry.register("memory", MemoryManager(database_url="sqlite:///:memory:"), overwrite=True)

    handler = MemoryHandler()
    store_cmd = ParsedCommand(
        raw="remember that I like dark mode",
        normalized="remember that i like dark mode",
        tokens=["remember", "that", "i", "like", "dark", "mode"],
    )
    store_result = await handler.handle(store_cmd, IntentResult(INTENT_MEMORY, 0.9, ["remember"], sub_intent="store"))
    assert store_result["status"] == "ok"
    assert "dark mode" in store_result["response"]

    recall_cmd = ParsedCommand(
        raw="what do you know about dark mode",
        normalized="what do you know about dark mode",
        tokens=["what", "do", "you", "know", "about", "dark", "mode"],
        is_question=True,
    )
    recall_result = await handler.handle(recall_cmd, IntentResult(INTENT_MEMORY, 0.9, ["know"], sub_intent="recall"))
    assert recall_result["status"] == "ok"
    assert "dark mode" in recall_result["response"]

    forget_cmd = ParsedCommand(
        raw="forget about dark mode",
        normalized="forget about dark mode",
        tokens=["forget", "about", "dark", "mode"],
    )
    forget_result = await handler.handle(forget_cmd, IntentResult(INTENT_MEMORY, 0.9, ["forget"], sub_intent="forget"))
    assert forget_result["status"] == "ok"
    assert "forgotten" in forget_result["response"].lower()

    registry.unregister("memory")


# ── Plugin Manager ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plugin_registration():
    from core.plugin_manager import PluginManager, GiniPlugin
    class DummyPlugin(GiniPlugin):
        name = "dummy"
        version = "1.0.0"

    pm = PluginManager()
    pm.register(DummyPlugin())
    assert pm.count == 1
    assert pm.get("dummy") is not None


@pytest.mark.asyncio
async def test_plugin_message_hook_override():
    from core.plugin_manager import PluginManager, GiniPlugin, PluginContext
    class OverridePlugin(GiniPlugin):
        name = "override"
        async def on_message(self, context: PluginContext):
            return "Plugin took over!"

    pm = PluginManager()
    pm.register(OverridePlugin())
    ctx = PluginContext(user_id="u1", session_id="s1", message="hi", emotion="neutral", metadata={})
    result = await pm.run_message_hooks(ctx)
    assert result == "Plugin took over!"


@pytest.mark.asyncio
async def test_plugin_message_hook_passthrough():
    from core.plugin_manager import PluginManager, GiniPlugin, PluginContext
    class PassPlugin(GiniPlugin):
        name = "pass"
        async def on_message(self, context: PluginContext):
            return None  # Pass through

    pm = PluginManager()
    pm.register(PassPlugin())
    ctx = PluginContext(user_id="u1", session_id="s1", message="hi", emotion="neutral", metadata={})
    result = await pm.run_message_hooks(ctx)
    assert result is None


@pytest.mark.asyncio
async def test_plugin_startup_shutdown_hooks():
    from core.plugin_manager import PluginManager, GiniPlugin
    log = []
    class TrackPlugin(GiniPlugin):
        name = "tracker"
        async def on_startup(self): log.append("start")
        async def on_shutdown(self): log.append("stop")

    pm = PluginManager()
    pm.register(TrackPlugin())
    await pm.run_startup_hooks()
    await pm.run_shutdown_hooks()
    assert log == ["start", "stop"]


# ── Lifecycle Manager ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_lifecycle_startup_shutdown():
    from core.lifecycle import LifecycleManager, LifecycleState
    events = []
    lm = LifecycleManager()
    lm.add_startup_hook("init", lambda: _record(events, "started"))
    lm.add_shutdown_hook("stop", lambda: _record(events, "stopped"))

    await lm.startup()
    assert lm.state == LifecycleState.RUNNING
    assert lm.is_running

    await lm.shutdown()
    assert lm.state == LifecycleState.STOPPED
    assert lm.is_stopped
    assert events == ["started", "stopped"]


@pytest.mark.asyncio
async def test_lifecycle_critical_failure():
    from core.lifecycle import LifecycleManager, LifecycleState
    async def fail(): raise RuntimeError("Boom")
    lm = LifecycleManager()
    lm.add_startup_hook("fail_hook", fail, critical=True)
    result = await lm.startup()
    assert result is False
    assert lm.state == LifecycleState.ERROR


@pytest.mark.asyncio
async def test_lifecycle_non_critical_failure_continues():
    from core.lifecycle import LifecycleManager, LifecycleState
    async def fail(): raise RuntimeError("Non-critical boom")
    async def ok(): pass
    lm = LifecycleManager()
    lm.add_startup_hook("fail", fail, critical=False)
    lm.add_startup_hook("ok", ok, critical=False)
    result = await lm.startup()
    assert lm.state == LifecycleState.RUNNING  # Still running despite non-critical fail


# ── GiniAssistant Engine ──────────────────────────────────────

@pytest.mark.asyncio
async def test_assistant_process_message_basic():
    from core.assistant import GiniAssistant
    from core.service_registry import ServiceRegistry
    reg = ServiceRegistry()
    assistant = GiniAssistant(registry=reg)
    await assistant.on_startup()
    result = await assistant.process_message("Hello Gini", "test_user")
    assert "response" in result
    assert result["emotion"] in ["positive", "negative", "neutral"]
    assert result["user_id"] == "test_user"


@pytest.mark.asyncio
async def test_assistant_emotion_detection_positive():
    from core.assistant import GiniAssistant
    from core.service_registry import ServiceRegistry
    assistant = GiniAssistant(registry=ServiceRegistry())
    await assistant.on_startup()
    result = await assistant.process_message("I am so happy and excited!", "u1")
    assert result["emotion"] == "positive"


@pytest.mark.asyncio
async def test_assistant_emotion_detection_negative():
    from core.assistant import GiniAssistant
    from core.service_registry import ServiceRegistry
    assistant = GiniAssistant(registry=ServiceRegistry())
    await assistant.on_startup()
    result = await assistant.process_message("I am very sad and frustrated", "u1")
    assert result["emotion"] == "negative"


@pytest.mark.asyncio
async def test_assistant_empty_message_safe():
    from core.assistant import GiniAssistant
    from core.service_registry import ServiceRegistry
    assistant = GiniAssistant(registry=ServiceRegistry())
    await assistant.on_startup()
    result = await assistant.process_message("   ", "u1")
    assert "response" in result   # Should not crash


@pytest.mark.asyncio
async def test_assistant_with_memory():
    from core.assistant import GiniAssistant
    from core.service_registry import ServiceRegistry
    from core.memory import MemoryManager
    reg = ServiceRegistry()
    reg.register("memory", MemoryManager())
    assistant = GiniAssistant(registry=reg)
    await assistant.on_startup()

    r1 = await assistant.process_message("Hello", "u1", "sess_1")
    r2 = await assistant.process_message("How are you?", "u1", r1["session_id"])
    assert r2["session_id"] == r1["session_id"]


@pytest.mark.asyncio
async def test_assistant_action_routing():
    from core.assistant import GiniAssistant
    from core.service_registry import ServiceRegistry
    from actions.action_router import ActionRouter
    reg = ServiceRegistry()
    reg.register("action_router", ActionRouter())
    assistant = GiniAssistant(registry=reg)
    await assistant.on_startup()
    result = await assistant.execute_action("smart_home.lights.on", {"room": "living_room"})
    assert result["status"] == "ok"
    assert result["module"] == "smart_home"


# ── Helpers ───────────────────────────────────────────────────

async def _record(log: list, value: str):
    log.append(value)
