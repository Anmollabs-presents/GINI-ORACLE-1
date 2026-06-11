import pytest

from actions.handlers.question_answer_handler import QuestionAnswerHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult, INTENT_QUESTION_ANSWER
from actions.fallback_handler import FallbackHandler


@pytest.mark.asyncio
async def test_question_answer_handler_definitions():
    handler = QuestionAnswerHandler()
    cmd = ParsedCommand(
        raw="What is photosynthesis?",
        normalized="what is photosynthesis",
        tokens=["what", "is", "photosynthesis"],
        is_question=True,
    )
    result = await handler.handle(cmd, IntentResult(INTENT_QUESTION_ANSWER, 0.9, ["what"], sub_intent="qa"))

    assert result["status"] == "ok"
    assert result["data"]["known"] is True
    assert "photosynthesis" in result["response"].lower()
    assert result["data"]["source"] == "knowledge"


@pytest.mark.asyncio
async def test_question_answer_handler_general_knowledge():
    handler = QuestionAnswerHandler()
    cmd = ParsedCommand(
        raw="Who is Albert Einstein?",
        normalized="who is albert einstein",
        tokens=["who", "is", "albert", "einstein"],
        is_question=True,
    )
    result = await handler.handle(cmd, IntentResult(INTENT_QUESTION_ANSWER, 0.9, ["who"], sub_intent="qa"))

    assert result["status"] == "ok"
    assert result["data"]["known"] is True
    assert "einstein" in result["response"].lower()
    assert result["data"]["source"] == "knowledge"


@pytest.mark.asyncio
async def test_question_answer_handler_fallback_for_unknown_topic():
    handler = QuestionAnswerHandler()
    cmd = ParsedCommand(
        raw="What is blorbity?",
        normalized="what is blorbity",
        tokens=["what", "is", "blorbity"],
        is_question=True,
    )
    result = await handler.handle(cmd, IntentResult(INTENT_QUESTION_ANSWER, 0.9, ["what"], sub_intent="qa"))

    assert result["status"] == "ok"
    assert result["data"]["known"] is False
    assert result["data"]["source"] == "fallback"
    assert "don't have enough knowledge" in result["response"].lower()


@pytest.mark.asyncio
async def test_fallback_handler_low_confidence():
    handler = FallbackHandler()
    cmd = ParsedCommand(
        raw="Play the thing",
        normalized="play the thing",
        tokens=["play", "the", "thing"],
    )
    response = await handler.handle(
        cmd,
        top_results=[IntentResult("media_control", 0.3, ["play"], sub_intent="play")],
        reason="low_confidence",
    )

    assert response["status"] == "fallback"
    assert "not confident" in response["response"].lower()
    assert response["intent"] == "unknown"
