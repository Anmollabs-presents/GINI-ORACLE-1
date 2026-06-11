# ============================================================
# GINI-ORACLE-1 — Pydantic Schemas
# models/schemas.py
# ============================================================

from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MessageRequest(BaseModel):
    """Incoming message from user to Gini."""
    user_id: str = Field(default="default", description="Unique user identifier")
    message: str = Field(..., min_length=1, max_length=4096, description="User's text input")
    session_id: Optional[str] = Field(default=None, description="Conversation session ID")


class MessageResponse(BaseModel):
    """Gini's response back to user."""
    response: str
    emotion: Literal["positive", "negative", "neutral"] = "neutral"
    user_id: str
    session_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=_utcnow)


class HealthResponse(BaseModel):
    """System health check response."""
    status: Literal["healthy", "degraded", "unhealthy"]
    app_name: str
    version: str
    environment: str
    checks_passed: int
    checks_failed: int
    timestamp: datetime = Field(default_factory=_utcnow)


__all__ = ["MessageRequest", "MessageResponse", "HealthResponse"]
