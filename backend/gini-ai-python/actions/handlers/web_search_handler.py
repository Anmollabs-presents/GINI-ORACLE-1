# ============================================================
# GINI-ORACLE-1 — Web Search Handler (Full Implementation)
# actions/handlers/web_search_handler.py
# ============================================================
"""
Handles web_search intents with real browser execution.

Sub-intents:
  google    — open Google search in browser
  youtube   — search or open YouTube
  navigate  — open a specific URL or website
  weather   — Google weather search
  news      — Google News
  maps      — Google Maps directions
  translate — Google Translate
  wikipedia — Wikipedia search
  search    — generic web search (defaults to Google)

Reuses:
  _extract_query()   — unchanged from original
  _STRIP_PREFIXES    — unchanged from original
  WebExecutor        — new OS-level web execution layer
"""

import re
from actions.handlers.base import BaseIntentHandler
from actions.command_parser import ParsedCommand
from actions.intent_detector import IntentResult
from actions.web_executor import get_web_executor, WebActionStatus


class WebSearchHandler(BaseIntentHandler):
    intent_name = "web_search"

    # ── Unchanged from original — preserved as required ───────
    _STRIP_PREFIXES = [
        "search for", "search", "google", "look up", "find",
        "browse", "navigate to", "go to", "open website",
        "youtube search", "youtube for", "play on youtube",
        "open", "show me",
        "youtube", "on youtube",
    ]

    def __init__(self):
        super().__init__()
        self._web = get_web_executor()

    async def handle(self, cmd: ParsedCommand, result: IntentResult) -> dict:
        sub = result.sub_intent or "search"

        dispatch = {
            "google":    self._handle_google,
            "youtube":   self._handle_youtube,
            "navigate":  self._handle_navigate,
            "weather":   self._handle_weather,
            "news":      self._handle_news,
            "maps":      self._handle_maps,
            "translate": self._handle_translate,
            "wikipedia": self._handle_wikipedia,
            "search":    self._handle_search,
        }
        fn = dispatch.get(sub, self._handle_search)
        return await fn(cmd)

    # ── Sub-handlers ─────────────────────────────────────────

    async def _handle_google(self, cmd: ParsedCommand) -> dict:
        query = self._extract_query(cmd)
        browser = self._extract_browser(cmd)
        r = self._web.google_search(query, browser)
        return self._from_web(r, "google")

    async def _handle_youtube(self, cmd: ParsedCommand) -> dict:
        query = self._extract_query(cmd)
        browser = self._extract_browser(cmd)
        r = self._web.youtube_search(query, browser)
        return self._from_web(r, "youtube")

    async def _handle_navigate(self, cmd: ParsedCommand) -> dict:
        # Priority: explicit URL entity → extracted site name
        url = cmd.entities.get("url", "")
        if not url:
            url = self._extract_query(cmd)
        if not url:
            return self._ok("Which website would you like me to open?", sub="navigate")
        browser = self._extract_browser(cmd)
        r = self._web.open_website(url, browser)
        return self._from_web(r, "navigate")

    async def _handle_weather(self, cmd: ParsedCommand) -> dict:
        query = self._extract_query(cmd)
        # Strip "weather" itself from query
        location = re.sub(r"\bweather\b", "", query).strip()
        r = self._web.weather_search(location)
        return self._from_web(r, "weather")

    async def _handle_news(self, cmd: ParsedCommand) -> dict:
        query = self._extract_query(cmd)
        topic = re.sub(r"\bnews\b", "", query).strip()
        r = self._web.news_search(topic)
        return self._from_web(r, "news")

    async def _handle_maps(self, cmd: ParsedCommand) -> dict:
        query = self._extract_query(cmd)
        destination = re.sub(
            r"\b(map|maps|navigate|directions|route|how to get to)\b", "", query
        ).strip()
        if not destination:
            return self._ok("Where would you like directions to?", sub="maps")
        r = self._web.maps_search(destination)
        return self._from_web(r, "maps")

    async def _handle_translate(self, cmd: ParsedCommand) -> dict:
        query = self._extract_query(cmd)
        text = re.sub(r"\btranslate\b", "", query).strip()
        if not text:
            return self._ok("What would you like me to translate?", sub="translate")
        r = self._web.translate(text)
        return self._from_web(r, "translate")

    async def _handle_wikipedia(self, cmd: ParsedCommand) -> dict:
        query = self._extract_query(cmd)
        r = self._web.wikipedia_search(query)
        return self._from_web(r, "wikipedia")

    async def _handle_search(self, cmd: ParsedCommand) -> dict:
        """Generic search — routes to correct engine based on context."""
        query = self._extract_query(cmd)

        if not query:
            return self._ok("What would you like me to search for?", sub="search")

        # Route to YouTube if video-related
        if cmd.has_any("youtube", "video", "watch", "play"):
            r = self._web.youtube_search(query)
            return self._from_web(r, "youtube")

        # Default: Google
        r = self._web.google_search(query)
        return self._from_web(r, "search")

    # ── Unchanged from original ────────────────────────────────

    def _extract_query(self, cmd: ParsedCommand) -> str:
        """Extract search query by stripping command prefixes."""
        text = cmd.normalized
        for prefix in self._STRIP_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                break
        return text.strip()

    # ── New helpers ────────────────────────────────────────────

    def _extract_browser(self, cmd: ParsedCommand) -> str:
        """Extract optional browser preference from command."""
        for browser in ["chrome", "firefox", "edge", "brave"]:
            if browser in cmd.normalized:
                return browser
        return ""

    def _from_web(self, result, sub: str) -> dict:
        """Convert WebActionResult to handler dict."""
        if result.success:
            return self._ok(
                result.message, sub=sub,
                url=result.url, query=result.query,
            )
        if result.status == WebActionStatus.INVALID_URL:
            return self._error(result.message, reason="invalid_url")
        if result.status == WebActionStatus.BLOCKED:
            return self._error("That URL is blocked for safety.", reason="blocked")
        if result.status == WebActionStatus.BROWSER_ERROR:
            return self._error(result.message, reason="browser_error")
        return self._error(
            result.message or "Web action failed.",
            reason=result.error or "unknown",
        )


__all__ = ["WebSearchHandler"]
