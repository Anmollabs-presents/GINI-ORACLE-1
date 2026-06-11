# ============================================================
# GINI-ORACLE-1 — Optional Local LLM Adapter
# assistant_core/local_llm_adapter.py
# ============================================================
"""
Optional adapter for local LLM backends.

Supported backends (all run locally, no API keys):
  - Ollama (https://ollama.ai) — run any model locally
  - Direct HTTP to any OpenAI-compatible local server

Configuration (all optional in .env):
  LOCAL_LLM_ENABLED=true/false   (default: false)
  LOCAL_LLM_BACKEND=ollama       (default: ollama)
  LOCAL_LLM_URL=http://localhost:11434
  LOCAL_LLM_MODEL=qwen2.5        (any model pulled in Ollama)

Usage:
  The adapter is DISABLED by default.
  Enable it by setting LOCAL_LLM_ENABLED=true in .env
  and running Ollama with your chosen model.

No API keys required. No internet required. Runs 100% locally.
"""

import json
import urllib.request
import urllib.error
from typing import Optional
from utils.logger import get_logger

log = get_logger(__name__)


class LocalLLMAdapter:
    """
    Adapter for locally-running LLM servers (Ollama etc).
    Disabled by default — only activates when LOCAL_LLM_ENABLED=true.
    """

    def __init__(self, url: str = "http://localhost:11434", model: str = "qwen2.5"):
        self.url = url.rstrip("/")
        self.model = model
        self._available: Optional[bool] = None  # None = not yet checked

    def is_available(self) -> bool:
        """Check if the local LLM server is reachable."""
        if self._available is not None:
            return self._available
        try:
            req = urllib.request.Request(f"{self.url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                self._available = resp.status == 200
        except Exception:
            self._available = False
        return self._available

    def generate(self, prompt: str, system: str = "") -> Optional[str]:
        """
        Send prompt to local LLM. Returns generated text or None on failure.
        Uses Ollama's /api/generate endpoint.
        """
        if not self.is_available():
            return None

        payload = {
            "model":  self.model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.url}/api/generate",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                text = result.get("response", "").strip()
                log.debug(f"LocalLLM ({self.model}) responded: {text[:80]}")
                return text if text else None
        except urllib.error.URLError as e:
            self._available = False  # Server went away
            log.warning(f"LocalLLM unreachable: {e}")
            return None
        except Exception as e:
            log.error(f"LocalLLM error: {e}")
            return None

    def chat(self, messages: list[dict], system: str = "") -> Optional[str]:
        """
        OpenAI-compatible chat endpoint (for Ollama's /api/chat).
        messages = [{"role": "user", "content": "..."}]
        """
        if not self.is_available():
            return None

        payload = {
            "model":    self.model,
            "messages": messages,
            "stream":   False,
        }
        if system:
            payload["messages"] = [{"role": "system", "content": system}] + messages

        try:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"{self.url}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                text = result.get("message", {}).get("content", "").strip()
                return text if text else None
        except Exception as e:
            log.warning(f"LocalLLM chat error: {e}")
            return None


# ── Factory ───────────────────────────────────────────────────

_adapter: Optional[LocalLLMAdapter] = None
_enabled: Optional[bool] = None


def get_local_llm() -> Optional[LocalLLMAdapter]:
    """
    Return the LocalLLMAdapter if LOCAL_LLM_ENABLED=true and Ollama is running.
    Returns None if disabled or unavailable.
    """
    global _adapter, _enabled

    if _enabled is None:
        import os
        _enabled = os.environ.get("LOCAL_LLM_ENABLED", "false").lower() in ("1", "true", "yes")
        if _enabled:
            url   = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434")
            model = os.environ.get("LOCAL_LLM_MODEL", "qwen2.5")
            _adapter = LocalLLMAdapter(url=url, model=model)
            if _adapter.is_available():
                log.info(f"🤖 Local LLM available: {model} @ {url}")
            else:
                log.info(f"Local LLM enabled in config but Ollama not running — skipping.")
                _adapter = None

    return _adapter if (_enabled and _adapter and _adapter.is_available()) else None


__all__ = ["LocalLLMAdapter", "get_local_llm"]
