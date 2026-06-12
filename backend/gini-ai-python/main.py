# ============================================================
# GINI-ORACLE-1 — Main Startup Entrypoint (Upgraded)
# main.py
# ============================================================

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from config.settings import settings
from utils.logger import get_logger
from utils.event_logger import get_event_logger
from core.bootstrap import bootstrap
from core.lifecycle import LifecycleManager
from core.assistant import GiniAssistant
from core.resilience_coordinator import get_resilience_coordinator
from models.schemas import MessageRequest, MessageResponse, HealthResponse

log = get_logger(__name__)
elog = get_event_logger()

# ── Lifespan (startup / shutdown) ────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan — delegates fully to bootstrap.
    Bootstrap handles: config → logger → registry →
                       memory → voice → actions → plugins → assistant → lifecycle
    """
    try:
        elog.lifecycle("app", "startup_begin", metadata={"version": settings.app_version})
        assistant, lifecycle = await bootstrap()
        app.state.assistant = assistant
        app.state.lifecycle = lifecycle
        log.info("🚀 Gini.ai is LIVE")
        elog.lifecycle("app", "running", metadata={"host": settings.host, "port": settings.port})
        yield
    except Exception as e:
        elog.failure(
            "app_startup_failed",
            str(e),
            service="main",
            exception=e,
            critical=True,
        )
        log.critical(f"💥 Bootstrap failed: {e}", exc_info=True)
        raise
    finally:
        # Graceful shutdown via lifecycle manager
        lifecycle: LifecycleManager = getattr(app.state, "lifecycle", None)
        if lifecycle and lifecycle.is_running:
            await lifecycle.shutdown()
        elog.lifecycle("app", "stopped")
        log.info("👋 Gini.ai stopped")


# ── FastAPI App ───────────────────────────────────────────────
app = FastAPI(
    title="GINI-AI Backend",
    description="Emotion-aware AI Operating System — controls smart home, hospital, vehicles & more",
    version=settings.app_version,
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Routes ───────────────────────────────────────────────────

@app.get("/", tags=["Root"])
async def root():
    return {
        "message": f"Welcome to {settings.app_name} 🌟",
        "version": settings.app_version,
        "environment": settings.app_env,
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """System health and lifecycle status."""
    from utils.health import run_health_checks
    report = run_health_checks()
    lifecycle: LifecycleManager = app.state.lifecycle

    api_key = (settings.api_key or "").strip().strip("[]")
    provider = (settings.ai_provider or "none").strip().strip("[]").lower()
    
    if api_key:
        provider_status = "ONLINE"
    elif provider == "none":
        provider_status = "OFFLINE"
    else:
        provider_status = "DEGRADED"

    return {
        "status": "healthy" if report.is_healthy else "degraded",
        "app_name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "provider_status": provider_status,
        "provider_name": provider,
        "model_name": settings.model_name,
        "checks_passed": len(report.passed),
        "checks_failed": len(report.failed),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/status", tags=["Health"])
async def system_status():
    """Detailed system status — assistant + lifecycle + services."""
    assistant: GiniAssistant = app.state.assistant
    lifecycle: LifecycleManager = app.state.lifecycle
    return {
        "assistant": assistant.status(),
        "lifecycle": lifecycle.status(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/resilience", tags=["Health"])
async def resilience_status():
    """Detailed resilience status and recent recovery actions."""
    coordinator = get_resilience_coordinator()
    return coordinator.get_status()


@app.post("/chat", response_model=MessageResponse, tags=["Chat"])
async def chat(request: MessageRequest):
    """Main chat endpoint — send a message to Gini."""
    assistant: GiniAssistant = app.state.assistant

    if not assistant.is_running:
        raise HTTPException(status_code=503, detail="Gini assistant is not running")

    result = await assistant.process_message(
        user_input=request.message,
        user_id=request.user_id,
        session_id=request.session_id,
    )

    return MessageResponse(
        response=result["response"],
        emotion=result["emotion"],
        user_id=result["user_id"],
        session_id=result.get("session_id"),
    )


@app.post("/action", tags=["Actions"])
async def execute_action(intent: str, payload: dict = {}):
    """Execute a device control action via Gini."""
    assistant: GiniAssistant = app.state.assistant
    result = await assistant.execute_action(intent=intent, payload=payload)
    return result


@app.get("/memory", tags=["Memory"])
async def get_memories(user_id: str = "default"):
    """Get all memories stored in SQLite for the user."""
    from core.memory import MemoryFactRecord
    assistant: GiniAssistant = app.state.assistant
    memory_manager = assistant._registry.resolve_optional("memory")
    if not memory_manager:
        return []
    with memory_manager._session() as db:
        facts = db.query(MemoryFactRecord).filter_by(user_id=user_id).order_by(MemoryFactRecord.added_at.desc()).all()
        return [
            {
                "topic": f.topic,
                "value": f.value,
                "category": f.category,
                "added_at": f.added_at.isoformat() if f.added_at else None
            }
            for f in facts
        ]


@app.get("/plugins", tags=["Plugins"])
async def list_plugins():
    """List all registered plugins."""
    from core.service_registry import get_registry
    registry = get_registry()
    plugin_manager = registry.resolve_optional("plugins")
    if not plugin_manager:
        return {"plugins": []}
    return {"plugins": plugin_manager.list_plugins()}


@app.get("/logs/events", tags=["Observability"])
async def recent_events(
    event_type: str = None,
    limit: int = 50,
):
    """
    Return recent structured events from the in-memory ring buffer.

    Query params:
      event_type  — filter by type: command | intent | execution_time |
                    failure | warning | voice | lifecycle
      limit       — max number of events to return (default 50, max 500)
    """
    limit = min(limit, 500)
    return {
        "events": elog.recent_events(limit=limit, event_type=event_type),
        "stats":  elog.stats(),
    }


@app.get("/logs/stats", tags=["Observability"])
async def event_stats():
    """Return event-type counts and ring-buffer stats."""
    return elog.stats()


# ── Startup Command ──────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
