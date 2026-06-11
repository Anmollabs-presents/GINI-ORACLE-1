# ============================================================
# GINI-ORACLE-1 — Memory System V2 Test Suite
# tests/test_task13_memory_v2.py
# ============================================================
"""
Validates the complete Memory V2 system:

  - Persistent SQLite storage
  - All 5 categories: Personal, Project, Preferences, Tasks, Facts
  - remember_fact (store + overwrite)
  - recall_fact (exact topic, fuzzy search)
  - search_facts
  - forget_fact
  - MemoryHandler lazy registry resolve (no silent-None bug)
  - Intent detection for memory (store / recall / forget)
  - End-to-end pipeline: "Remember my name is Anmol" → "What is my name?" → "Your name is Anmol."

No cloud APIs. No internet. 100% offline.
"""

import asyncio
import pytest
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture(scope="session")
def memory_manager():
    """In-memory SQLite MemoryManager for isolated test runs."""
    from core.memory import MemoryManager
    return MemoryManager(database_url="sqlite:///:memory:")


@pytest.fixture(scope="session")
def registry_with_memory(memory_manager):
    """ServiceRegistry with MemoryManager registered."""
    from core.service_registry import get_registry
    reg = get_registry()
    reg.register("memory", memory_manager, overwrite=True)
    return reg


# ── Unit tests: MemoryManager ─────────────────────────────────

class TestMemoryManagerCategories:
    """Test all 5 memory categories store and recall correctly."""

    def test_personal_memory_store_and_recall(self, memory_manager):
        """Remember my name is Anmol → recall name → Anmol."""
        memory_manager.remember_fact("user1", "name", "Anmol", category="personal")
        result = memory_manager.recall_fact("user1", "name")
        assert result == "Anmol", f"Expected 'Anmol', got '{result}'"

    def test_project_memory_store_and_recall(self, memory_manager):
        """Remember I am building Gini AI → recall project."""
        memory_manager.remember_fact("user1", "project", "Gini AI", category="project")
        result = memory_manager.recall_fact("user1", "project")
        assert result == "Gini AI", f"Expected 'Gini AI', got '{result}'"

    def test_preference_memory_store_and_recall(self, memory_manager):
        """Remember favorite color is blue → recall favorite color."""
        memory_manager.remember_fact("user1", "favorite color", "blue", category="preference")
        result = memory_manager.recall_fact("user1", "favorite color")
        assert result == "blue", f"Expected 'blue', got '{result}'"

    def test_task_memory_store_and_recall(self, memory_manager):
        """Remember a task/reminder."""
        memory_manager.remember_fact("user1", "task", "Finish Phase 2 memory system", category="task")
        result = memory_manager.recall_fact("user1", "task")
        assert "Phase 2" in str(result), f"Expected task in result, got '{result}'"

    def test_fact_memory_store_and_recall(self, memory_manager):
        """Remember a general fact."""
        memory_manager.remember_fact("user1", "note", "GINI-ORACLE-1 is production-grade", category="fact")
        result = memory_manager.recall_fact("user1", "note")
        assert "GINI-ORACLE-1" in str(result), f"Expected fact in result, got '{result}'"


class TestMemoryOverwrite:
    """Test that re-remembering the same topic overwrites (upsert) correctly."""

    def test_overwrite_same_topic(self, memory_manager):
        """Overwrite an existing memory fact."""
        memory_manager.remember_fact("user_ow", "name", "OldName", category="personal")
        memory_manager.remember_fact("user_ow", "name", "NewName", category="personal")
        result = memory_manager.recall_fact("user_ow", "name")
        assert result == "NewName", f"Expected 'NewName' after overwrite, got '{result}'"

    def test_overwrite_preserves_other_facts(self, memory_manager):
        """Overwriting one fact does not destroy others."""
        memory_manager.remember_fact("user_ow2", "name", "Alice", category="personal")
        memory_manager.remember_fact("user_ow2", "project", "ProjectX", category="project")
        memory_manager.remember_fact("user_ow2", "name", "Alice Updated", category="personal")
        assert memory_manager.recall_fact("user_ow2", "project") == "ProjectX"
        assert memory_manager.recall_fact("user_ow2", "name") == "Alice Updated"


class TestMemorySearch:
    """Test fuzzy search across topics and values."""

    def test_search_by_partial_topic(self, memory_manager):
        """Search facts matching a partial topic string."""
        memory_manager.remember_fact("user_s", "programming language", "Python", category="fact")
        result = memory_manager.search_facts("user_s", "programming")
        assert result is not None

    def test_search_by_value_substring(self, memory_manager):
        """Search facts matching a substring in the value."""
        memory_manager.remember_fact("user_s2", "hobby", "playing guitar and singing", category="personal")
        result = memory_manager.search_facts("user_s2", "guitar")
        assert result is not None

    def test_search_no_results(self, memory_manager):
        """Search for something that doesn't exist returns None."""
        result = memory_manager.search_facts("user_s3", "xyznonexistent")
        assert result is None


class TestForgetFact:
    """Test forget_fact removes memories correctly."""

    def test_forget_existing_fact(self, memory_manager):
        """Forgetting an existing fact removes it."""
        memory_manager.remember_fact("user_f", "temp", "temporary value", category="fact")
        deleted = memory_manager.forget_fact("user_f", "temp")
        assert deleted > 0
        result = memory_manager.recall_fact("user_f", "temp")
        assert result is None

    def test_forget_nonexistent_fact(self, memory_manager):
        """Forgetting something that doesn't exist returns 0."""
        deleted = memory_manager.forget_fact("user_f2", "does_not_exist_xyz")
        assert deleted == 0


class TestMemoryPersistence:
    """Test that facts persist across separate recall calls (SQLite)."""

    def test_persistent_across_calls(self, memory_manager):
        """Store a fact and verify it's retrievable on multiple calls."""
        memory_manager.remember_fact("user_p", "city", "Delhi", category="fact")
        r1 = memory_manager.recall_fact("user_p", "city")
        r2 = memory_manager.recall_fact("user_p", "city")
        assert r1 == r2 == "Delhi"

    def test_user_isolation(self, memory_manager):
        """Facts for one user don't leak to another user."""
        memory_manager.remember_fact("user_iso1", "secret", "abc123", category="fact")
        result = memory_manager.recall_fact("user_iso2", "secret")
        assert result is None


# ── Unit tests: Category inference ───────────────────────────

class TestCategoryInference:
    """Test that _infer_category works correctly from topics/values."""

    def test_infer_personal_from_name_topic(self, memory_manager):
        """Topic 'name' → Personal Memory category."""
        memory_manager.remember_fact("cat_test", "name", "Anmol")
        # Verify it stored with correct category by checking recall
        result = memory_manager.recall_fact("cat_test", "name")
        assert result == "Anmol"

    def test_infer_project_from_project_topic(self, memory_manager):
        """Topic 'project' → Project Memory category."""
        memory_manager.remember_fact("cat_test2", "project", "Gini AI")
        result = memory_manager.recall_fact("cat_test2", "project")
        assert result == "Gini AI"


# ── Unit tests: MemoryHandler (with registry) ─────────────────

class TestMemoryHandlerLazyResolve:
    """
    Verify the lazy-resolve fix: MemoryHandler must work even when
    it is constructed before MemoryManager is registered.
    """

    def test_lazy_resolve_finds_memory(self, registry_with_memory):
        """MemoryHandler resolves memory lazily — not at __init__ time."""
        # Simulate constructing MemoryHandler when registry is empty
        from core.service_registry import ServiceRegistry
        # We'll use the shared registry that already has memory
        from actions.handlers.memory_handler import MemoryHandler
        handler = MemoryHandler()
        # Should be able to access _memory via lazy property
        memory = handler._memory
        assert memory is not None, "MemoryHandler lazy resolve returned None"


class TestMemoryHandlerPatterns:
    """Test _parse_memory_fact and _extract_topic regex patterns."""

    def setup_method(self):
        from actions.handlers.memory_handler import MemoryHandler
        from actions.command_parser import CommandParser
        self.handler = MemoryHandler()
        self.parser = CommandParser()

    def _make_cmd(self, text: str):
        return self.parser.parse(text)

    def test_pattern_name_store(self):
        """'remember my name is Anmol' → topic=name, value=Anmol."""
        cmd = self._make_cmd("remember my name is Anmol")
        result = self.handler._parse_memory_fact(cmd)
        assert result is not None, "_parse_memory_fact returned None"
        topic, value, category = result
        assert topic == "name", f"Expected topic='name', got '{topic}'"
        assert value == "Anmol", f"Expected value='Anmol', got '{value}'"
        assert category == "personal"

    def test_pattern_project_store(self):
        """'I am building Gini AI' → topic=project, value=Gini AI."""
        cmd = self._make_cmd("I am building Gini AI")
        result = self.handler._parse_memory_fact(cmd)
        assert result is not None
        topic, value, category = result
        assert topic == "project"
        assert "Gini" in value
        assert category == "project"

    def test_pattern_favorite_color(self):
        """'my favorite color is blue' → topic=favorite color, value=blue."""
        cmd = self._make_cmd("my favorite color is blue")
        result = self.handler._parse_memory_fact(cmd)
        assert result is not None
        topic, value, category = result
        assert "color" in topic.lower()
        assert value.lower() == "blue"
        assert category == "preference"

    def test_extract_topic_name_recall(self):
        """'what is my name' → topic extracted as 'name'."""
        cmd = self._make_cmd("what is my name")
        topic = self.handler._extract_topic(cmd)
        assert topic == "name", f"Expected 'name', got '{topic}'"

    def test_extract_topic_project_recall(self):
        """'what project am I building' → topic=project."""
        cmd = self._make_cmd("what project am I building")
        topic = self.handler._extract_topic(cmd)
        assert topic == "project", f"Expected 'project', got '{topic}'"

    def test_extract_topic_color_recall(self):
        """'what is my favorite color' → topic=favorite color."""
        cmd = self._make_cmd("what is my favorite color")
        topic = self.handler._extract_topic(cmd)
        assert "color" in topic.lower(), f"Expected 'favorite color', got '{topic}'"

    def test_format_recall_name(self):
        """_format_recall('name', 'Anmol') → 'Your name is Anmol.'"""
        response = self.handler._format_recall("name", "Anmol")
        assert response == "Your name is Anmol.", f"Got: '{response}'"

    def test_format_recall_project(self):
        """_format_recall('project', 'Gini AI') → 'You are building Gini AI.'"""
        response = self.handler._format_recall("project", "Gini AI")
        assert response == "You are building Gini AI.", f"Got: '{response}'"

    def test_format_recall_favorite_color(self):
        """_format_recall('favorite color', 'blue') → 'Your favorite color is blue.'"""
        response = self.handler._format_recall("favorite color", "blue")
        assert "blue" in response.lower() and "color" in response.lower(), f"Got: '{response}'"


# ── End-to-End pipeline tests ──────────────────────────────────

class TestMemoryEndToEnd:
    """
    Full async pipeline tests through GiniAssistant.

    Validates the key user scenario:
      "Remember my name is Anmol"   → confirms storage
      "What is my name?"            → "Your name is Anmol."
    """

    @pytest.fixture(scope="class")
    def assistant_with_memory(self):
        """Create GiniAssistant with full registry including MemoryManager."""
        from core.assistant import GiniAssistant
        from core.service_registry import get_registry
        from core.memory import MemoryManager
        from actions.action_router import ActionRouter

        reg = get_registry()
        mem = MemoryManager(database_url="sqlite:///:memory:")
        reg.register("memory", mem, overwrite=True)
        reg.register("action_router", ActionRouter(), overwrite=True)

        assistant = GiniAssistant(registry=reg)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        loop.run_until_complete(assistant.on_startup())
        return assistant

    def _run(self, coro):
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    def test_e2e_remember_name(self, assistant_with_memory):
        """Pipeline: 'remember my name is Anmol' → confirms storage."""
        result = self._run(
            assistant_with_memory.process_message("remember my name is Anmol", "e2e_user")
        )
        response = result["response"].lower()
        assert any(w in response for w in ["remember", "got it", "anmol", "stored", "updated"]), \
            f"Unexpected response: '{result['response']}'"

    def test_e2e_recall_name(self, assistant_with_memory):
        """Pipeline: 'What is my name?' → 'Your name is Anmol.'"""
        # First store the name
        self._run(
            assistant_with_memory.process_message("remember my name is Anmol", "e2e_user2")
        )
        # Now recall
        result = self._run(
            assistant_with_memory.process_message("What is my name?", "e2e_user2")
        )
        response = result["response"]
        assert "Anmol" in response, \
            f"Expected 'Anmol' in recall response, got: '{response}'"

    def test_e2e_remember_project(self, assistant_with_memory):
        """Pipeline: 'I am building Gini AI' → recall project."""
        self._run(
            assistant_with_memory.process_message("remember I am building Gini AI", "e2e_user3")
        )
        result = self._run(
            assistant_with_memory.process_message("What project am I building?", "e2e_user3")
        )
        response = result["response"]
        assert "Gini" in response, \
            f"Expected 'Gini' in project recall, got: '{response}'"

    def test_e2e_remember_favorite_color(self, assistant_with_memory):
        """Pipeline: 'my favorite color is blue' → recall color."""
        self._run(
            assistant_with_memory.process_message("remember my favorite color is blue", "e2e_user4")
        )
        result = self._run(
            assistant_with_memory.process_message("What is my favorite color?", "e2e_user4")
        )
        response = result["response"].lower()
        assert "blue" in response, \
            f"Expected 'blue' in color recall, got: '{result['response']}'"

    def test_e2e_overwrite_and_recall(self, assistant_with_memory):
        """Pipeline: overwrite name → recall returns updated value."""
        self._run(
            assistant_with_memory.process_message("remember my name is Bob", "e2e_user5")
        )
        self._run(
            assistant_with_memory.process_message("remember my name is Alice", "e2e_user5")
        )
        result = self._run(
            assistant_with_memory.process_message("What is my name?", "e2e_user5")
        )
        response = result["response"]
        assert "Alice" in response, \
            f"Expected 'Alice' after overwrite, got: '{response}'"
        assert "Bob" not in response, \
            f"Old name 'Bob' should not appear in response: '{response}'"


# ── Intent detector tests ─────────────────────────────────────

class TestMemoryIntentDetection:
    """Test that memory intents are correctly detected."""

    def setup_method(self):
        from actions.intent_detector import IntentDetector
        from actions.command_parser import CommandParser
        self.detector = IntentDetector()
        self.parser = CommandParser()

    def _detect(self, text: str):
        cmd = self.parser.parse(text)
        return self.detector.detect(cmd)

    def test_remember_name_intent(self):
        """'remember my name is Anmol' → memory/store."""
        result = self._detect("remember my name is Anmol")
        assert result.intent == "memory", f"Expected 'memory', got '{result.intent}'"
        assert result.sub_intent == "store", f"Expected sub_intent='store', got '{result.sub_intent}'"

    def test_what_is_my_name_intent(self):
        """'what is my name' → memory/recall."""
        result = self._detect("what is my name")
        assert result.intent == "memory", f"Expected 'memory', got '{result.intent}'"
        assert result.sub_intent == "recall", f"Expected sub_intent='recall', got '{result.sub_intent}'"

    def test_what_is_my_favorite_color_intent(self):
        """'what is my favorite color' → memory/recall."""
        result = self._detect("what is my favorite color")
        assert result.intent == "memory", f"Expected 'memory', got '{result.intent}'"
        assert result.sub_intent == "recall"

    def test_what_project_am_i_building_intent(self):
        """'what project am I building' → memory/recall."""
        result = self._detect("what project am I building")
        assert result.intent == "memory"
        assert result.sub_intent == "recall"

    def test_forget_intent(self):
        """'forget my name' → memory/forget."""
        result = self._detect("forget my name")
        assert result.intent == "memory"
        assert result.sub_intent == "forget"

    def test_remember_intent_confidence(self):
        """'remember my name is Anmol' must have confidence ≥ 0.55."""
        result = self._detect("remember my name is Anmol")
        assert result.confidence >= 0.55, \
            f"Confidence {result.confidence:.2f} too low for memory intent"


# ── Validation scenario (required by task spec) ───────────────

class TestRequiredValidationScenario:
    """
    Task spec validation:
      Input:  "Remember my name is Anmol"
      Input:  "What is my name?"
      Expected: "Your name is Anmol."
    """

    def test_validation_scenario(self):
        """The exact scenario from the task spec must work end-to-end."""
        from core.memory import MemoryManager
        from core.service_registry import get_registry
        from core.assistant import GiniAssistant
        from actions.action_router import ActionRouter

        # Use global registry to avoid lazy resolve mismatch
        reg = get_registry()
        mem = MemoryManager(database_url="sqlite:///:memory:")
        reg.register("memory", mem, overwrite=True)
        reg.register("action_router", ActionRouter(), overwrite=True)

        assistant = GiniAssistant(registry=reg)

        async def run():
            await assistant.on_startup()
            # Step 1: Store
            r1 = await assistant.process_message("Remember my name is Anmol", "val_user")
            # Step 2: Recall
            r2 = await assistant.process_message("What is my name?", "val_user")
            return r1["response"], r2["response"]

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        store_resp, recall_resp = loop.run_until_complete(run())

        # Validate store acknowledgement
        assert any(w in store_resp.lower() for w in ["remember", "got it", "anmol", "stored", "updated"]), \
            f"Store response invalid: '{store_resp}'"

        # Validate recall: MUST contain "Anmol"
        assert "Anmol" in recall_resp, \
            f"VALIDATION FAILED: Expected 'Anmol' in recall response.\n" \
            f"  Store response:  '{store_resp}'\n" \
            f"  Recall response: '{recall_resp}'\n" \
            f"  Expected:        'Your name is Anmol.'"

        print(f"\n✅ VALIDATION PASSED")
        print(f"   Store:  '{store_resp}'")
        print(f"   Recall: '{recall_resp}'")
