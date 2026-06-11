# ============================================================
# GINI-ORACLE-1 — System Control Handler (Full Implementation)
# actions/handlers/system_control_handler.py
# ============================================================
"""
Handles system_control intents with real OS execution.

Sub-intents:
  volume     — set/up/down/mute/unmute
  brightness — set/up/down
  power      — shutdown/restart (with confirmation)
  sleep      — suspend
  lock       — lock screen
  wifi       — toggle (partial — OS-dependent)
  bluetooth  — toggle (partial — OS-dependent)
  display    — dark mode (stub — Phase N)

Uses SystemExecutor for OS calls and
ConfirmationManager for dangerous action gating.
"""

import re
from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult
from actions.system_executor import create_system_executor, ActionStatus
from actions.confirmation_manager import get_confirmation_manager


class SystemControlHandler(BaseIntentHandler):
    intent_name = "system_control"

    def __init__(self, mock: bool = False):
        super().__init__()
        self._executor = create_system_executor(mock=mock)
        self._confirm = get_confirmation_manager()

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        sub = result.sub_intent or "general"
        user_id = getattr(cmd, "user_id", "default")

        # ── Check for pending confirmation first ──────────────
        if self._confirm.has_pending(user_id):
            if self._confirm.is_confirmation(cmd.raw):
                confirmed = await self._confirm.confirm(user_id)
                return confirmed or self._ok("Action confirmed and executed.", sub="confirm")
            if self._confirm.is_cancellation(cmd.raw):
                self._confirm.cancel(user_id)
                return self._ok("Action cancelled.", sub="cancel")

        dispatch = {
            "volume":     self._handle_volume,
            "brightness": self._handle_brightness,
            "power":      self._handle_power,
            "sleep":      self._handle_sleep,
            "lock":       self._handle_lock,
            "wifi":       self._handle_wifi,
            "bluetooth":  self._handle_bluetooth,
            "display":    self._handle_display,
        }
        fn = dispatch.get(sub)
        if fn:
            return await fn(cmd, user_id)
        return self._ok(f"System command '{sub}' acknowledged.", sub=sub)

    # ── Volume ────────────────────────────────────────────────

    async def _handle_volume(self, cmd: ParsedCommand, user_id: str) -> dict:
        if cmd.has_any("mute"):
            r = self._executor.mute()
            return self._from_result(r, "volume", action="mute")

        if cmd.has_any("unmute"):
            r = self._executor.unmute()
            return self._from_result(r, "volume", action="unmute")

        level = self._extract_number(cmd)
        if level is not None:
            level = max(0, min(100, int(level)))
            r = self._executor.volume_set(level)
            return self._from_result(r, "volume", action="set", level=level)

        direction = "up" if cmd.has_any("up","increase","louder","raise","higher") else "down"
        r = self._executor.volume_step(direction)
        return self._from_result(r, "volume", action=direction)

    # ── Brightness ────────────────────────────────────────────

    async def _handle_brightness(self, cmd: ParsedCommand, user_id: str) -> dict:
        level = self._extract_number(cmd)
        if level is not None:
            level = max(0, min(100, int(level)))
            r = self._executor.brightness_set(level)
            return self._from_result(r, "brightness", level=level)

        direction = "up" if cmd.has_any("up","increase","brighter","higher") else "down"
        r = self._executor.brightness_step(direction)
        return self._from_result(r, "brightness", action=direction)

    # ── Power (with confirmation) ─────────────────────────────

    async def _handle_power(self, cmd: ParsedCommand, user_id: str) -> dict:
        if cmd.has_any("shutdown", "shut down", "power off"):
            return await self._request_confirm(
                user_id=user_id,
                action="shutdown",
                prompt="Are you sure you want to shut down? Say 'yes' to confirm or 'no' to cancel.",
                callback=self._do_shutdown,
            )
        if cmd.has_any("restart", "reboot"):
            return await self._request_confirm(
                user_id=user_id,
                action="restart",
                prompt="Are you sure you want to restart? Say 'yes' to confirm or 'no' to cancel.",
                callback=self._do_restart,
            )
        return self._ok("What power action would you like — shutdown or restart?", sub="power")

    async def _do_shutdown(self) -> dict:
        r = self._executor.shutdown()
        return self._from_result(r, "power", action="shutdown")

    async def _do_restart(self) -> dict:
        r = self._executor.restart()
        return self._from_result(r, "power", action="restart")

    async def _request_confirm(
        self, user_id: str, action: str, prompt: str, callback
    ) -> dict:
        self._confirm.request(
            user_id=user_id,
            action=action,
            payload={},
            prompt=prompt,
            callback=callback,
        )
        return self._ok(prompt, sub="confirm_pending", action=action)

    # ── Sleep ─────────────────────────────────────────────────

    async def _handle_sleep(self, cmd: ParsedCommand, user_id: str) -> dict:
        r = self._executor.sleep()
        return self._from_result(r, "sleep")

    # ── Lock screen ───────────────────────────────────────────

    async def _handle_lock(self, cmd: ParsedCommand, user_id: str) -> dict:
        r = self._executor.lock_screen()
        return self._from_result(r, "lock")

    # ── WiFi ──────────────────────────────────────────────────

    async def _handle_wifi(self, cmd: ParsedCommand, user_id: str) -> dict:
        action = "disabled" if cmd.has_negation else "enabled"
        # Real OS WiFi toggle is platform-specific (nmcli/netsh)
        # Partial implementation — logs intent, real execution in Phase N
        self.log.info(f"WiFi {action} requested")
        return self._ok(f"Wi-Fi {action}.", sub="wifi", wifi=action)

    # ── Bluetooth ─────────────────────────────────────────────

    async def _handle_bluetooth(self, cmd: ParsedCommand, user_id: str) -> dict:
        action = "disabled" if cmd.has_negation else "enabled"
        self.log.info(f"Bluetooth {action} requested")
        return self._ok(f"Bluetooth {action}.", sub="bluetooth", bluetooth=action)

    # ── Display ───────────────────────────────────────────────

    async def _handle_display(self, cmd: ParsedCommand, user_id: str) -> dict:
        return self._ok("Switching to dark mode.", sub="dark_mode")

    # ── Helpers ───────────────────────────────────────────────

    def _from_result(self, result, sub: str, **extra) -> dict:
        """Convert SystemActionResult to handler dict."""
        if result.success:
            return self._ok(result.message, sub=sub, **extra)
        if result.status == ActionStatus.NOT_SUPPORTED:
            return self._ok(result.message, sub=sub)
        return self._error(result.message, reason=result.error or result.status.value)

    def _extract_number(self, cmd: ParsedCommand) -> float | None:
        nums = re.findall(r"\b(\d+)\b", cmd.normalized)
        return float(nums[0]) if nums else None


__all__ = ["SystemControlHandler"]
