# ============================================================
# GINI-ORACLE-1 — Foundation Tests
# tests/test_foundation.py
# ============================================================

import pytest
import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_config_loads():
    """Config system must load without errors."""
    from config.settings import settings
    assert settings.app_name == "GINI-AI"
    assert settings.app_version is not None


def test_logger_initializes():
    """Logger must initialize without errors."""
    from utils.logger import get_logger
    log = get_logger("test")
    assert log is not None


def test_health_check_runs():
    """Health check system must run and return a report."""
    from utils.health import run_health_checks
    report = run_health_checks()
    assert report is not None
    assert hasattr(report, "is_healthy")


def test_assistant_initializes():
    """Core assistant must initialize."""
    from core.assistant import GiniAssistant
    assistant = GiniAssistant()
    assert assistant is not None


def test_action_router_initializes():
    """Action router must initialize with all modules."""
    from actions.action_router import ActionRouter
    router = ActionRouter()
    assert router is not None
    assert "smart_home" in router.modules
    assert "hospital" in router.modules
    assert "vehicle" in router.modules
    assert "mobile" in router.modules


def test_voice_engine_initializes():
    """Voice engine must initialize."""
    from voice.voice_engine import VoiceEngine
    engine = VoiceEngine()
    assert engine is not None


@pytest.mark.asyncio
async def test_assistant_processes_message():
    """Assistant must process a basic message."""
    from core.assistant import GiniAssistant
    assistant = GiniAssistant()
    result = await assistant.process_message("Hello Gini!", "test_user")
    assert "response" in result
    assert "emotion" in result
    assert result["emotion"] in ["positive", "negative", "neutral"]
