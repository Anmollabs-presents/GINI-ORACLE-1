# ============================================================
# GINI-ORACLE-1 — App Control Handler (Full Implementation)
# actions/handlers/app_control_handler.py
# ============================================================
"""
Handles app_control intents:
  open   — launch application or browser URL
  close  — graceful terminate
  kill   — force kill
  focus  — bring window to foreground
  browser— open specific browser
  install— redirect to store (stub)

Uses AppRegistry for app resolution and
ProcessManager for safe OS execution.
"""

import re
from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult
from actions.app_registry import get_app_registry
from actions.process_manager import get_process_manager, ProcessResult
from core.resilience import FailureMode
from core.resilience_coordinator import get_resilience_coordinator


class AppControlHandler(BaseIntentHandler):
    intent_name = "app_control"

    # ── Spoken name → registry alias mapping ─────────────────
    _SPOKEN_ALIASES = {
        "youtube":       "youtube",
        "spotify":       "spotify",
        "chrome":        "chrome",
        "google chrome": "chrome",
        "firefox":       "firefox",
        "mozilla":       "firefox",
        "edge":          "edge",
        "brave":         "brave",
        "vlc":           "vlc",
        "whatsapp":      "whatsapp",
        "telegram":      "telegram",
        "discord":       "discord",
        "zoom":          "zoom",
        "notepad":       "notepad",
        "calculator":    "calculator",
        "calc":          "calculator",
        "files":         "files",
        "explorer":      "files",
        "file manager":  "files",
        "task manager":  "task manager",
        "settings":      "settings",
        "vscode":        "vs code",
        "vs code":       "vs code",
        "code":          "vs code",
        "terminal":      "terminal",
        "cmd":           "terminal",
        "powershell":    "terminal",
    }

    def __init__(self):
        super().__init__()
        self._registry = get_app_registry()
        self._pm = get_process_manager()

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        sub = result.sub_intent or "open"
        app_name = self._extract_app(cmd)

        dispatch = {
            "open":    self._handle_open,
            "close":   self._handle_close,
            "kill":    self._handle_kill,
            "focus":   self._handle_focus,
            "browser": self._handle_browser,
            "install": self._handle_install,
        }

        handler_fn = dispatch.get(sub, self._handle_open)
        return await handler_fn(cmd, app_name)

    # ── Sub-handlers ─────────────────────────────────────────

    async def _handle_open(self, cmd: ParsedCommand, app_name: str) -> dict:
        if not app_name:
            recovery = await get_resilience_coordinator().handle_error(
                FailureMode.INVALID_COMMAND,
                "Missing app name",
                context={"command": cmd.raw, "service": "app_control"},
            )
            return self._ok(
                "Which app would you like me to open?",
                sub="open",
                recovery=recovery,
            )

        # Check for URL in command
        url = cmd.entities.get("url")
        action = self._pm.launch(app_name, url=url)

        if action.result == ProcessResult.SUCCESS:
            return self._ok(action.message, sub="open", app=action.app_name, pid=action.pid)

        if action.result == ProcessResult.ALREADY_RUNNING:
            return self._ok(action.message, sub="focus", app=action.app_name)

        if action.result == ProcessResult.NOT_FOUND:
            recovery = await get_resilience_coordinator().handle_error(
                FailureMode.APP_NOT_FOUND,
                action.message,
                context={"app_name": app_name, "service": "app_control"},
            )
            return self._ok(
                recovery["message"],
                sub="open", app=app_name, recovery=recovery,
            )

        if action.result == ProcessResult.PERMISSION_ERROR:
            return self._error(
                f"I don't have permission to open {app_name.title()}.",
                reason="permission_denied",
            )

        return self._error(
            f"Something went wrong opening {app_name.title()}.",
            reason=action.error or "unknown",
        )

    async def _handle_close(self, cmd: ParsedCommand, app_name: str) -> dict:
        if not app_name:
            return self._ok("Which app should I close?", sub="close")

        action = self._pm.close(app_name)

        if action.result == ProcessResult.SUCCESS:
            return self._ok(action.message, sub="close", app=action.app_name)

        if action.result == ProcessResult.NOT_RUNNING:
            return self._ok(
                f"{app_name.title()} doesn't seem to be open right now.",
                sub="close", app=app_name,
            )

        if action.result == ProcessResult.PROTECTED:
            return self._error(
                f"I can't close that — it's a system process.",
                reason="protected",
            )

        return self._error(
            f"Couldn't close {app_name.title()}. {action.error or ''}",
            reason=action.error or "unknown",
        )

    async def _handle_kill(self, cmd: ParsedCommand, app_name: str) -> dict:
        if not app_name:
            return self._ok("Which app should I force-close?", sub="kill")

        action = self._pm.kill(app_name)

        if action.result == ProcessResult.SUCCESS:
            return self._ok(action.message, sub="kill", app=action.app_name)

        if action.result == ProcessResult.PROTECTED:
            return self._error(
                f"I won't kill that — it's a protected system process.",
                reason="protected",
            )

        if action.result == ProcessResult.NOT_RUNNING:
            return self._ok(
                f"{app_name.title()} is not running.",
                sub="kill", app=app_name,
            )

        return self._error(
            f"Could not kill {app_name.title()}.",
            reason=action.error or "unknown",
        )

    async def _handle_focus(self, cmd: ParsedCommand, app_name: str) -> dict:
        if not app_name:
            return self._ok("Which app should I switch to?", sub="focus")

        # Launch if not running
        if not self._pm.is_running(app_name):
            return await self._handle_open(cmd, app_name)

        action = self._pm.focus(app_name)

        if action.result in (ProcessResult.SUCCESS, ProcessResult.ALREADY_RUNNING):
            return self._ok(action.message, sub="focus", app=action.app_name)

        if action.result == ProcessResult.NOT_RUNNING:
            return await self._handle_open(cmd, app_name)

        return self._error(
            f"Could not switch to {app_name.title()}.",
            reason=action.error or "unknown",
        )

    async def _handle_browser(self, cmd: ParsedCommand, app_name: str) -> dict:
        """Open browser — with optional URL."""
        browser = app_name if app_name in {"chrome","firefox","edge","brave"} else "chrome"
        url = cmd.entities.get("url", "")
        action = self._pm.launch(browser, url=url or None)
        if action.result in (ProcessResult.SUCCESS, ProcessResult.ALREADY_RUNNING):
            return self._ok(action.message, sub="browser", app=action.app_name, url=url)
        recovery = await get_resilience_coordinator().handle_error(
            FailureMode.BROWSER_FAILURE,
            action.error or action.message,
            context={"browser_name": browser, "service": "app_control"},
        )
        return self._ok(recovery["message"], sub="browser", url=url, recovery=recovery)

    async def _handle_install(self, cmd: ParsedCommand, app_name: str) -> dict:
        if app_name:
            return self._ok(
                f"Searching for '{app_name.title()}' in the app store.",
                sub="install", app=app_name,
            )
        return self._ok("What app would you like to install?", sub="install")

    # ── App name extraction ───────────────────────────────────

    def _extract_app(self, cmd: ParsedCommand) -> str:
        """
        Extract app name from command.
        Priority: known aliases → regex extraction → raw token
        """
        text = cmd.normalized

        # 1. Multi-word alias check (longest first)
        for alias in sorted(self._SPOKEN_ALIASES, key=len, reverse=True):
            if alias in text:
                return self._SPOKEN_ALIASES[alias]

        # 2. Regex: word after verb
        match = re.search(
            r"(?:open|launch|start|close|quit|exit|kill|focus|switch to|bring up)\s+(\w[\w\s]*?)(?:\s+(?:app|application|browser|please|now))?$",
            text,
        )
        if match:
            extracted = match.group(1).strip()
            if extracted and extracted not in {"the", "a", "an", "my"}:
                return self._SPOKEN_ALIASES.get(extracted, extracted)

        # 3. Single-word fallback — last word in command
        tokens = cmd.tokens
        stop_words = {"open","launch","start","close","quit","exit","kill","focus",
                      "the","a","an","app","please","now","my","this"}
        candidates = [t for t in tokens if t not in stop_words]
        if candidates:
            last = candidates[-1]
            return self._SPOKEN_ALIASES.get(last, last)

        return ""


__all__ = ["AppControlHandler"]
