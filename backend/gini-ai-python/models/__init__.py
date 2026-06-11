# models/__init__.py
# Gini data models — Pydantic schemas for API and internal use

from .schemas import MessageRequest, MessageResponse, HealthResponse

__all__ = ["MessageRequest", "MessageResponse", "HealthResponse"]
