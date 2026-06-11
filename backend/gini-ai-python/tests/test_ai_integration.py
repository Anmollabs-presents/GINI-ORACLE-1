# ============================================================
# GINI-ORACLE-1 — AI Integration and Hybrid Routing Tests
# tests/test_ai_integration.py
# ============================================================

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from config.settings import settings
from core.memory import MemoryManager
from core.service_registry import get_registry
from core.assistant import GiniAssistant
from assistant_core.ai_provider import (
    get_ai_provider,
    BaseAIProvider,
    MockAIProvider,
    GeminiAIProvider,
    OpenAIProvider,
    AnthropicProvider,
    OllamaAIProvider,
)
from assistant_core.identity import IdentityManager
from assistant_core.intent_dispatch import dispatch


# --- Helper for Async Testing ---
def _run(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# --- AI Provider Tests ---

def test_ai_provider_factory():
    """Verify that get_ai_provider returns appropriate providers and fallbacks."""
    # Temporarily clean key
    original_key = settings.api_key
    try:
        settings.api_key = ""
        provider = get_ai_provider("gemini")
        assert isinstance(provider, MockAIProvider)

        provider = get_ai_provider("ollama")
        assert isinstance(provider, OllamaAIProvider)

        settings.api_key = "test_key"
        provider = get_ai_provider("gemini")
        assert isinstance(provider, GeminiAIProvider)

        provider = get_ai_provider("openai")
        assert isinstance(provider, OpenAIProvider)

        provider = get_ai_provider("anthropic")
        assert isinstance(provider, AnthropicProvider)
        
        provider = get_ai_provider("unknown_provider")
        assert isinstance(provider, MockAIProvider)
    finally:
        settings.api_key = original_key


@pytest.mark.asyncio
async def test_gemini_provider_retry():
    """Verify Gemini provider retries on transient errors."""
    provider = GeminiAIProvider(api_key="test_key")
    
    # Mock httpx AsyncClient post to fail twice, then succeed
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [{
            "content": {
                "parts": [{"text": "Hello from Gemini"}]
            }
        }]
    }

    with patch("httpx.AsyncClient.post") as mock_post:
        # 2 failures (httpx.HTTPError) then 1 success
        mock_post.side_effect = [
            httpx.HTTPStatusError("Rate Limit", request=MagicMock(), response=MagicMock(status_code=429)),
            httpx.TimeoutException("Timeout"),
            mock_response
        ]
        
        # Patch sleep to speed up test
        with patch("asyncio.sleep", return_value=None):
            resp = await provider.generate_response("Hi")
            assert resp == "Hello from Gemini"
            assert mock_post.call_count == 3


# --- Relevance-based Memory Retrieval Tests ---

def test_relevance_based_memory_retrieval():
    """Verify memory retrieval scores and returns relevant facts."""
    memory_manager = MemoryManager(database_url="sqlite:///:memory:")
    user_id = "test_rel_user"
    
    # Store different facts
    memory_manager.remember_fact(user_id, "name", "Anmol", category="personal")
    memory_manager.remember_fact(user_id, "project", "Gini-Oracle Upgrade", category="project")
    memory_manager.remember_fact(user_id, "favorite color", "blue", category="preference")
    memory_manager.remember_fact(user_id, "hobby", "playing tennis", category="preference")
    memory_manager.remember_fact(user_id, "programming language", "Python coding", category="fact")
    
    # Query matching project
    memories = memory_manager.get_relevant_memories(user_id, "tell me about my project", limit=2)
    assert "project" in memories
    assert "Gini-Oracle Upgrade" in memories["project"]
    
    # Query with active topic
    memories = memory_manager.get_relevant_memories(user_id, "tell me more", active_topic="Python", limit=2)
    assert "facts" in memories
    assert "Python coding" in memories["facts"]


def test_active_topic_tracking():
    """Verify active topic is correctly identified from session turns."""
    memory_manager = MemoryManager(database_url="sqlite:///:memory:")
    session = memory_manager.get_or_create_session("user_topic", "session_topic")
    
    # No history
    assert memory_manager.get_active_topic("session_topic") is None
    
    # With history: "Explain Python"
    memory_manager.add_turn("session_topic", "user", "Explain Python")
    memory_manager.add_turn("session_topic", "assistant", "Python is a language")
    
    topic = memory_manager.get_active_topic("session_topic")
    assert topic == "python"

    # Add turn with stops: "and what else?" -> should fall back to previous topic "python"
    memory_manager.add_turn("session_topic", "user", "and what else?")
    topic = memory_manager.get_active_topic("session_topic")
    assert topic == "python"


# --- Identity Prompt Safety Tests ---

def test_identity_prompt_safety():
    """Verify prompt structure and rule protection."""
    memories = {
        "personal": "name: Anmol",
        "project": "project: Gini-Oracle"
    }
    instruction = IdentityManager.get_system_instruction(memories)
    
    # Verify name & persona present
    assert "Gini" in instruction
    assert "Female AI Assistant" in instruction
    
    # Verify safety rules present
    assert "NEVER reveal" in instruction or "internal instructions" in instruction
    
    # Verify memory injection present
    assert "Anmol" in instruction
    assert "Gini-Oracle" in instruction


# --- Hybrid Routing Tests ---

@pytest.mark.asyncio
async def test_hybrid_routing_stages():
    """Test the complete hybrid routing flow with mocked components."""
    # Mock routing engine
    mock_routing = MagicMock()
    
    # 1. Greetings -> ResponseEngine (Stage 1)
    # response engine handles "hello" without routing engine
    res = await dispatch("hello", routing_engine=mock_routing)
    assert "hello" in res.lower() or "hi" in res.lower() or "gini" in res.lower()
    
    # 2. Command -> RoutingEngine handles directly (Stage 2)
    mock_route_result = MagicMock()
    mock_route_result.intent = "memory"
    mock_route_result.confidence = 0.95
    mock_route_result.response = "Got it! Remember name: Anmol"
    mock_routing.route = AsyncMock(return_value=mock_route_result)
    
    res = await dispatch("remember my name is Anmol", routing_engine=mock_routing)
    assert "remember name" in res.lower() or "got it" in res.lower()

    # 3. Question -> AI Layer (Stage 3)
    # Setup mock AI provider response
    mock_ai = AsyncMock()
    mock_ai.generate_response.return_value = "Python is a high-level programming language."
    
    # Configure mock_routing to return a low-confidence QA intent to trigger Stage 3 AI
    mock_route_result_qa = MagicMock()
    mock_route_result_qa.intent = "question_answer"
    mock_route_result_qa.confidence = 0.4
    mock_route_result_qa.response = ""
    mock_routing.route = AsyncMock(return_value=mock_route_result_qa)
    
    with patch("assistant_core.intent_dispatch.get_ai_provider", return_value=mock_ai):
        with patch("config.settings.settings.api_key", "mock_key"):
            res = await dispatch("explain python", routing_engine=mock_routing)
            assert "Python is a high-level" in res
