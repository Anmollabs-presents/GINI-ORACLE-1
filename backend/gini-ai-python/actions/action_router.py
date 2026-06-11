# ============================================================
# GINI-ORACLE-1 — Action Router (Refactored)
# actions/action_router.py
# ============================================================
"""
ActionRouter now serves two roles:
  1. NL command routing → delegates to RoutingEngine
  2. Device control routing → smart_home / hospital / vehicle / mobile
     (kept from Phase 1, to be expanded in Phase 3)
"""

from typing import Optional
from actions.routing_engine import RoutingEngine, RouteResult
from utils.logger import get_logger
from config.settings import settings

log = get_logger(__name__)


class ActionRouter:
    """
    Unified router for Gini.ai.
    - Natural language commands → RoutingEngine
    - Device intents → module handlers (Phase 3)
    """

    def __init__(self):
        # NL routing engine
        self._routing_engine = RoutingEngine()

        # Device module flags
        self.modules = {
            "smart_home": settings.smart_home_enabled,
            "hospital":   settings.hospital_module_enabled,
            "vehicle":    settings.vehicle_module_enabled,
            "mobile":     settings.mobile_module_enabled,
        }
        log.info(
            f"⚡ ActionRouter initialized | "
            f"modules={[k for k,v in self.modules.items() if v]}"
        )

    async def route_command(
        self,
        raw_input: str,
        user_id: str = "unknown",
        session_id: Optional[str] = None,
    ) -> dict:
        """
        Route a natural language command through the full pipeline.
        Returns a RouteResult dict.
        """
        result: RouteResult = await self._routing_engine.route(
            raw_input,
            user_id=user_id,
            session_id=session_id,
        )
        log.info(
            f"🎯 Routed: '{raw_input[:40]}' → "
            f"{result.intent} ({result.confidence:.2f}) | {result.status}"
        )
        return result.to_dict()

    async def route(self, intent: str, payload: dict) -> dict:
        """
        Route a structured device control intent.
        Used by GiniAssistant.execute_action().
        """
        log.info(f"🔀 Device intent: {intent}")

        if intent.startswith("smart_home") and self.modules["smart_home"]:
            return await self._handle_smart_home(payload)
        elif intent.startswith("hospital") and self.modules["hospital"]:
            return await self._handle_hospital(payload)
        elif intent.startswith("vehicle") and self.modules["vehicle"]:
            return await self._handle_vehicle(payload)
        elif intent.startswith("mobile") and self.modules["mobile"]:
            return await self._handle_mobile(payload)
        else:
            log.warning(f"No device handler for intent: {intent}")
            return {"status": "unhandled", "intent": intent}

    # ── Device handlers (Phase 3 full implementation) ─────────

    async def _handle_smart_home(self, payload: dict) -> dict:
        return {"status": "ok", "module": "smart_home", "payload": payload}

    async def _handle_hospital(self, payload: dict) -> dict:
        return {"status": "ok", "module": "hospital", "payload": payload}

    async def _handle_vehicle(self, payload: dict) -> dict:
        return {"status": "ok", "module": "vehicle", "payload": payload}

    async def _handle_mobile(self, payload: dict) -> dict:
        return {"status": "ok", "module": "mobile", "payload": payload}

    @property
    def routing_engine(self) -> RoutingEngine:
        return self._routing_engine


__all__ = ["ActionRouter"]
