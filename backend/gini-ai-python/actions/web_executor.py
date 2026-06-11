# ============================================================
# GINI-ORACLE-1 — Web Executor
# actions/web_executor.py
# ============================================================
"""
Handles all web interaction for Gini.ai:
  - URL sanitization and validation
  - Google search URL building
  - YouTube search URL building
  - Safe browser open via stdlib webbrowser
  - Specific browser targeting (Chrome, Firefox, Edge)
  - Error recovery with fallback strategies

Design:
  - Uses stdlib only: webbrowser, urllib.parse, re
  - Reuses _launch_url() from ProcessManager for browser-specific opens
  - Never raises — always returns WebActionResult
  - Validates all URLs before opening (blocks dangerous schemes)
"""

import re
import webbrowser
import urllib.parse
from dataclasses import dataclass
from typing import Optional
from enum import Enum

from utils.logger import get_logger
from core.web_resilience import get_web_resilience

log = get_logger(__name__)


# ── Safe URL constants ────────────────────────────────────────

# Only these schemes are allowed to open
ALLOWED_SCHEMES = {"http", "https"}

# Blocked patterns (security)
BLOCKED_PATTERNS = [
    r"javascript:",
    r"data:",
    r"vbscript:",
    r"file://",
    r"about:",
    r"chrome-extension://",
]

# Search URL templates
GOOGLE_SEARCH_URL  = "https://www.google.com/search?q={query}"
YOUTUBE_SEARCH_URL = "https://www.youtube.com/results?search_query={query}"
YOUTUBE_BASE_URL   = "https://www.youtube.com"
MAPS_URL           = "https://www.google.com/maps/search/{query}"
WEATHER_URL        = "https://www.google.com/search?q=weather+{query}"
NEWS_URL           = "https://news.google.com/search?q={query}"
WIKIPEDIA_URL      = "https://en.wikipedia.org/wiki/Special:Search?search={query}"
TRANSLATE_URL      = "https://translate.google.com/?text={query}"

# Common website shortcuts
WEBSITE_SHORTCUTS = {
    "google":     "https://www.google.com",
    "youtube":    "https://www.youtube.com",
    "facebook":   "https://www.facebook.com",
    "twitter":    "https://www.twitter.com",
    "instagram":  "https://www.instagram.com",
    "reddit":     "https://www.reddit.com",
    "github":     "https://www.github.com",
    "gmail":      "https://mail.google.com",
    "amazon":     "https://www.amazon.in",
    "flipkart":   "https://www.flipkart.com",
    "netflix":    "https://www.netflix.com",
    "whatsapp":   "https://web.whatsapp.com",
    "wikipedia":  "https://www.wikipedia.org",
    "linkedin":   "https://www.linkedin.com",
    "maps":       "https://maps.google.com",
    "news":       "https://news.google.com",
    "chatgpt":    "https://chat.openai.com",
    "claude":     "https://claude.ai",
}


class WebActionStatus(str, Enum):
    SUCCESS       = "success"
    INVALID_URL   = "invalid_url"
    BLOCKED       = "blocked"
    BROWSER_ERROR = "browser_error"
    ERROR         = "error"


@dataclass
class WebActionResult:
    """Result of a web interaction action."""
    status: WebActionStatus
    message: str
    url: str = ""
    query: str = ""
    browser_used: str = "default"
    error: Optional[str] = None
    recovery: Optional[dict] = None

    @property
    def success(self) -> bool:
        return self.status == WebActionStatus.SUCCESS

    def to_dict(self) -> dict:
        return {
            "status":       self.status.value,
            "message":      self.message,
            "url":          self.url,
            "query":        self.query,
            "browser_used": self.browser_used,
            "error":        self.error,
            "recovery":     self.recovery,
        }


class URLSanitizer:
    """
    Validates and normalizes URLs before opening.
    Blocks dangerous schemes and malformed inputs.
    """

    def sanitize(self, raw_url: str) -> tuple[bool, str, str]:
        """
        Validate and normalize a URL.

        Returns:
            (is_safe: bool, clean_url: str, reason: str)
        """
        if not raw_url or not raw_url.strip():
            return False, "", "empty_url"

        url = raw_url.strip()

        # Block dangerous patterns first
        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, url, re.IGNORECASE):
                log.warning(f"Blocked dangerous URL pattern: {url[:80]}")
                return False, "", f"blocked_pattern:{pattern}"

        # Add scheme if missing
        if not re.match(r"^https?://", url, re.IGNORECASE):
            if url.startswith("www."):
                url = "https://" + url
            elif "." in url and not url.startswith("/"):
                url = "https://" + url
            else:
                return False, "", "no_scheme"

        # Parse and validate
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme.lower() not in ALLOWED_SCHEMES:
                return False, "", f"scheme_not_allowed:{parsed.scheme}"
            if not parsed.netloc:
                return False, "", "no_netloc"
            # Basic netloc sanity check
            if not re.match(r"^[a-zA-Z0-9.\-:@]+$", parsed.netloc):
                return False, "", "invalid_netloc"
        except Exception as e:
            return False, "", f"parse_error:{e}"

        return True, url, "ok"

    def is_website_shortcut(self, text: str) -> Optional[str]:
        """Check if text matches a known website shortcut. Returns URL or None."""
        return WEBSITE_SHORTCUTS.get(text.lower().strip())


class WebExecutor:
    """
    Executes web interactions safely.
    Builds URLs, validates them, and opens them in the browser.
    """

    def __init__(self):
        self._sanitizer = URLSanitizer()
        log.info("🌐 WebExecutor initialized")

    # ── Core open ─────────────────────────────────────────────

    def open_url(
        self, url: str, browser: Optional[str] = None
    ) -> WebActionResult:
        """
        Open a URL in the default or specified browser.
        Validates URL before opening.
        """
        is_safe, clean_url, reason = self._sanitizer.sanitize(url)
        if not is_safe:
            recovery = self._invalid_url_recovery(url)
            return WebActionResult(
                status=WebActionStatus.INVALID_URL,
                message=recovery["message"],
                url=url,
                error=reason,
                recovery=recovery,
            )

        return self._open(clean_url, browser)

    def _invalid_url_recovery(self, url: str) -> dict:
        """Build a recovery payload for malformed or blocked URLs."""
        fixed_url = get_web_resilience()._fix_common_url_issues(url)
        if fixed_url and fixed_url != url:
            return {
                "status": "degraded",
                "failure_mode": "invalid_command",
                "fallback_mode": "retry",
                "message": f"Fixed URL format. Trying: {fixed_url}",
                "suggested_url": fixed_url,
                "can_retry": True,
            }
        if url and not any(marker in url for marker in ("://", ".")):
            encoded = urllib.parse.quote_plus(url)
            return {
                "status": "degraded",
                "failure_mode": "invalid_command",
                "fallback_mode": "search",
                "message": f"Opening search results for: {url}",
                "suggested_url": GOOGLE_SEARCH_URL.format(query=encoded),
                "can_retry": True,
            }
        return {
            "status": "error",
            "failure_mode": "invalid_command",
            "fallback_mode": "abort",
            "message": "That URL does not look safe to open.",
            "can_retry": False,
        }

    def _open(self, url: str, browser: Optional[str] = None) -> WebActionResult:
        """Actually open a validated URL."""
        try:
            if browser:
                return self._open_specific_browser(url, browser)

            # Default browser
            opened = webbrowser.open(url)
            if opened:
                log.info(f"🌐 Opened: {url[:80]}")
                return WebActionResult(
                    status=WebActionStatus.SUCCESS,
                    message=f"Opening {self._display_url(url)}",
                    url=url,
                    browser_used="default",
                )
            # webbrowser.open returned False — try new tab
            opened = webbrowser.open_new_tab(url)
            if opened:
                return WebActionResult(
                    status=WebActionStatus.SUCCESS,
                    message=f"Opening {self._display_url(url)} in new tab.",
                    url=url,
                    browser_used="default",
                )
            recovery = self._browser_recovery("default", "webbrowser_returned_false")
            return WebActionResult(
                status=WebActionStatus.BROWSER_ERROR,
                message="Could not open browser. Is a browser installed?",
                url=url,
                error="webbrowser_returned_false",
                recovery=recovery,
            )
        except Exception as e:
            log.error(f"Browser open error: {e}")
            # Error recovery — try fallback
            return self._fallback_open(url, str(e))

    def _open_specific_browser(self, url: str, browser_name: str) -> WebActionResult:
        """Open URL in a named browser using webbrowser registry."""
        browser_map = {
            "chrome":  ["google-chrome", "chrome", "chromium-browser"],
            "firefox": ["firefox", "mozilla"],
            "edge":    ["microsoft-edge", "msedge"],
            "brave":   ["brave-browser", "brave"],
        }
        browser_cmds = browser_map.get(browser_name.lower(), [])

        for cmd in browser_cmds:
            try:
                b = webbrowser.get(cmd)
                b.open(url)
                log.info(f"🌐 Opened in {cmd}: {url[:60]}")
                return WebActionResult(
                    status=WebActionStatus.SUCCESS,
                    message=f"Opening in {browser_name.title()}.",
                    url=url,
                    browser_used=browser_name,
                )
            except Exception:
                continue

        # Fallback to default
        log.warning(f"{browser_name} not found — using default browser")
        return self._open(url)

    def _fallback_open(self, url: str, original_error: str) -> WebActionResult:
        """Last resort: try os.startfile or xdg-open."""
        import sys, subprocess, shutil
        try:
            if sys.platform == "win32":
                import os
                os.startfile(url)
                return WebActionResult(
                    WebActionStatus.SUCCESS,
                    f"Opening {self._display_url(url)}",
                    url=url, browser_used="os.startfile",
                )
            elif sys.platform.startswith("linux"):
                if shutil.which("xdg-open"):
                    subprocess.Popen(["xdg-open", url])
                    return WebActionResult(
                        WebActionStatus.SUCCESS,
                        f"Opening {self._display_url(url)}",
                        url=url, browser_used="xdg-open",
                    )
            elif sys.platform == "darwin":
                subprocess.Popen(["open", url])
                return WebActionResult(
                    WebActionStatus.SUCCESS,
                    f"Opening {self._display_url(url)}",
                    url=url, browser_used="open",
                )
        except Exception as e2:
            pass

        recovery = self._browser_recovery("default", original_error)
        return WebActionResult(
            status=WebActionStatus.BROWSER_ERROR,
            message="Could not open the browser. Please try manually.",
            url=url,
            error=f"original={original_error}",
            recovery=recovery,
        )

    def _browser_recovery(self, browser_name: str, error: str) -> dict:
        """Build a synchronous browser recovery payload."""
        manager = get_web_resilience()
        manager.failed_browsers.add(browser_name)
        alt_browser = manager._find_alternative_browser()
        if alt_browser:
            return {
                "status": "degraded",
                "failure_mode": "browser_failure",
                "fallback_mode": "try_browser",
                "message": f"Browser failed. Try {alt_browser} instead.",
                "suggestions": [alt_browser],
                "can_retry": True,
            }
        return {
            "status": "degraded",
            "failure_mode": "browser_failure",
            "fallback_mode": "text_mode",
            "message": "No browser could be opened. Showing the result in text mode.",
            "suggestions": [],
            "can_retry": False,
        }

    # ── Search builders ───────────────────────────────────────

    def google_search(self, query: str, browser: Optional[str] = None) -> WebActionResult:
        """Open a Google search for the query."""
        if not query.strip():
            return WebActionResult(
                WebActionStatus.ERROR,
                "What would you like to search for?",
            )
        encoded = urllib.parse.quote_plus(query.strip())
        url = GOOGLE_SEARCH_URL.format(query=encoded)
        result = self._open(url, browser)
        result.query = query
        result.message = f"Searching Google for '{query}'."
        return result

    def youtube_search(self, query: str, browser: Optional[str] = None) -> WebActionResult:
        """Search YouTube for a query."""
        if not query.strip():
            # Just open YouTube
            result = self._open(YOUTUBE_BASE_URL, browser)
            result.message = "Opening YouTube."
            return result
        encoded = urllib.parse.quote_plus(query.strip())
        url = YOUTUBE_SEARCH_URL.format(query=encoded)
        result = self._open(url, browser)
        result.query = query
        result.message = f"Searching YouTube for '{query}'."
        return result

    def open_website(self, site: str, browser: Optional[str] = None) -> WebActionResult:
        """
        Open a website by name or URL.
        Checks shortcuts first, then validates as URL.
        """
        site = site.strip()

        # Check shortcuts
        shortcut_url = self._sanitizer.is_website_shortcut(site)
        if shortcut_url:
            result = self._open(shortcut_url, browser)
            result.message = f"Opening {site.title()}."
            return result

        # Try as direct URL
        is_safe, clean_url, reason = self._sanitizer.sanitize(site)
        if is_safe:
            result = self._open(clean_url, browser)
            result.message = f"Opening {self._display_url(clean_url)}."
            return result

        # Last resort: Google search for it
        log.info(f"URL not recognized — falling back to Google search: '{site}'")
        return self.google_search(site, browser)

    def weather_search(self, location: str = "") -> WebActionResult:
        """Search Google for weather."""
        q = f"weather {location}".strip() if location else "weather today"
        encoded = urllib.parse.quote_plus(q)
        url = WEATHER_URL.format(query=encoded)
        result = self._open(url)
        result.query = q
        result.message = f"Fetching weather{' for ' + location if location else ''}."
        return result

    def news_search(self, topic: str = "") -> WebActionResult:
        """Open Google News for a topic."""
        if topic:
            encoded = urllib.parse.quote_plus(topic)
            url = NEWS_URL.format(query=encoded)
            result = self._open(url)
            result.query = topic
            result.message = f"Fetching news about '{topic}'."
        else:
            result = self._open("https://news.google.com")
            result.message = "Opening Google News."
        return result

    def maps_search(self, destination: str) -> WebActionResult:
        """Open Google Maps for a destination."""
        encoded = urllib.parse.quote_plus(destination.strip())
        url = MAPS_URL.format(query=encoded)
        result = self._open(url)
        result.query = destination
        result.message = f"Getting directions to '{destination}'."
        return result

    def translate(self, text: str) -> WebActionResult:
        """Open Google Translate for the given text."""
        encoded = urllib.parse.quote_plus(text.strip())
        url = TRANSLATE_URL.format(query=encoded)
        result = self._open(url)
        result.query = text
        result.message = f"Translating: '{text[:40]}'."
        return result

    def wikipedia_search(self, query: str) -> WebActionResult:
        """Search Wikipedia."""
        encoded = urllib.parse.quote_plus(query.strip())
        url = WIKIPEDIA_URL.format(query=encoded)
        result = self._open(url)
        result.query = query
        result.message = f"Looking up '{query}' on Wikipedia."
        return result

    # ── Helper ────────────────────────────────────────────────

    def _display_url(self, url: str) -> str:
        """Return a short human-readable form of a URL."""
        try:
            parsed = urllib.parse.urlparse(url)
            return parsed.netloc or url[:40]
        except Exception:
            return url[:40]


# Singleton
_executor: Optional[WebExecutor] = None

def get_web_executor() -> WebExecutor:
    global _executor
    if _executor is None:
        _executor = WebExecutor()
    return _executor


__all__ = [
    "WebExecutor", "WebActionResult", "WebActionStatus",
    "URLSanitizer", "get_web_executor",
    "WEBSITE_SHORTCUTS", "ALLOWED_SCHEMES",
]
