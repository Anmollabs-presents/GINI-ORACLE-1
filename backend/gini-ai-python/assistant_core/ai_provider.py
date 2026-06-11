# assistant_core/ai_provider.py
# ============================================================
# GINI-ORACLE-1 — AI Provider Abstraction Layer
# ============================================================
"""
Provides a unified interface to call external/internal LLM services.
Includes concrete implementations for:
  - Gemini (via HTTPX)
  - OpenAI (via HTTPX)
  - Anthropic (via HTTPX)
  - Ollama (via HTTPX)
  - Mock (fallback/testing)

Implements robust error handling (exponential backoff retry).
"""

import json
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import httpx
from config.settings import settings
from utils.logger import get_logger

log = get_logger(__name__)


class BaseAIProvider(ABC):
    """
    Abstract base class for all AI Providers.
    """

    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        """
        Generate a text response for the given prompt.
        
        Args:
            prompt: The current user message.
            system_instruction: Optional developer-defined instructions.
            history: Optional conversation context list:
                     [{"role": "user"/"assistant", "content": "..."}]
        """
        pass


class MockAIProvider(BaseAIProvider):
    """
    Fallback provider for testing and offline modes when API keys are absent.
    """

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        log.info(f"MockAIProvider used for prompt: {prompt[:30]}...")
        return f"This is Gini, a memory-aware AI assistant. You said: '{prompt}'"


class GeminiAIProvider(BaseAIProvider):
    """
    Google Gemini AI Provider utilizing the API via HTTPX.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-1.5-flash",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 15.0,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        model = self.model_name
        if not model.startswith("models/"):
            model = f"models/{model}"

        url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={self.api_key}"
        
        # Build contents
        contents = []
        if history:
            for item in history:
                role = item.get("role", "user")
                if role == "assistant":
                    role = "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": item.get("content", "")}]
                })
        
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            }
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        headers = {"Content-Type": "application/json"}

        # Retry logic with exponential backoff
        retries = 3
        delay = 1.0
        async with httpx.AsyncClient() as client:
            for attempt in range(retries):
                try:
                    response = await client.post(
                        url, json=payload, headers=headers, timeout=self.timeout
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    # Parse response
                    text = result["candidates"][0]["content"]["parts"][0]["text"]
                    return text.strip()
                except (httpx.HTTPError, httpx.TimeoutException, asyncio.TimeoutError, KeyError, IndexError) as e:
                    log.warning(f"Gemini API request failed on attempt {attempt+1}: {e}")
                    if attempt == retries - 1:
                        log.error(f"Gemini API error: {e}")
                        raise e
                    await asyncio.sleep(delay)
                    delay *= 2.0
        
        raise RuntimeError("Failed to generate response from Gemini API.")


class OpenAIProvider(BaseAIProvider):
    """
    OpenAI-compatible Provider utilizing the API via HTTPX.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-3.5-turbo",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 15.0,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        
        if history:
            for item in history:
                role = item.get("role", "user")
                if role == "model":
                    role = "assistant"
                messages.append({
                    "role": role,
                    "content": item.get("content", "")
                })
        
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # Retry logic with exponential backoff
        retries = 3
        delay = 1.0
        async with httpx.AsyncClient() as client:
            for attempt in range(retries):
                try:
                    response = await client.post(
                        url, json=payload, headers=headers, timeout=self.timeout
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    text = result["choices"][0]["message"]["content"]
                    return text.strip()
                except (httpx.HTTPError, httpx.TimeoutException, asyncio.TimeoutError, KeyError, IndexError) as e:
                    log.warning(f"OpenAI API request failed on attempt {attempt+1}: {e}")
                    if attempt == retries - 1:
                        log.error(f"OpenAI API error: {e}")
                        raise e
                    await asyncio.sleep(delay)
                    delay *= 2.0

        raise RuntimeError("Failed to generate response from OpenAI API.")


class AnthropicProvider(BaseAIProvider):
    """
    Anthropic Claude Provider utilizing the API via HTTPX.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "claude-3-haiku-20240307",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 15.0,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        url = "https://api.anthropic.com/v1/messages"
        
        messages = []
        if history:
            for item in history:
                role = item.get("role", "user")
                if role in ("assistant", "model"):
                    role = "assistant"
                messages.append({
                    "role": role,
                    "content": item.get("content", "")
                })
        
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        if system_instruction:
            payload["system"] = system_instruction

        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        retries = 3
        delay = 1.0
        async with httpx.AsyncClient() as client:
            for attempt in range(retries):
                try:
                    response = await client.post(
                        url, json=payload, headers=headers, timeout=self.timeout
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    text = result["content"][0]["text"]
                    return text.strip()
                except (httpx.HTTPError, httpx.TimeoutException, asyncio.TimeoutError, KeyError, IndexError) as e:
                    log.warning(f"Anthropic API request failed on attempt {attempt+1}: {e}")
                    if attempt == retries - 1:
                        log.error(f"Anthropic API error: {e}")
                        raise e
                    await asyncio.sleep(delay)
                    delay *= 2.0

        raise RuntimeError("Failed to generate response from Anthropic API.")


class OllamaAIProvider(BaseAIProvider):
    """
    Ollama Provider running locally.
    """

    def __init__(
        self,
        url: str = "http://localhost:11434",
        model_name: str = "qwen2.5",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 30.0,
    ):
        self.url = url.rstrip("/")
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        endpoint = f"{self.url}/api/chat"
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        
        if history:
            for item in history:
                role = item.get("role", "user")
                if role == "model":
                    role = "assistant"
                messages.append({
                    "role": role,
                    "content": item.get("content", "")
                })
        
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            }
        }

        headers = {"Content-Type": "application/json"}

        retries = 3
        delay = 1.0
        async with httpx.AsyncClient() as client:
            for attempt in range(retries):
                try:
                    response = await client.post(
                        endpoint, json=payload, headers=headers, timeout=self.timeout
                    )
                    response.raise_for_status()
                    result = response.json()
                    
                    text = result.get("message", {}).get("content", "")
                    return text.strip()
                except (httpx.HTTPError, httpx.TimeoutException, asyncio.TimeoutError, KeyError, IndexError) as e:
                    log.warning(f"Ollama API request failed on attempt {attempt+1}: {e}")
                    if attempt == retries - 1:
                        log.error(f"Ollama API error: {e}")
                        raise e
                    await asyncio.sleep(delay)
                    delay *= 2.0

        raise RuntimeError("Failed to generate response from Ollama API.")


class XAIProvider(BaseAIProvider):
    """
    xAI (Grok) Provider — OpenAI-compatible API at api.x.ai.
    Uses xai-... API keys.
    """

    BASE_URL = "https://api.x.ai/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        model_name: str = "grok-3-mini",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 20.0,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        if history:
            for item in history:
                role = item.get("role", "user")
                if role == "model":
                    role = "assistant"
                messages.append({"role": role, "content": item.get("content", "")})

        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        retries = 3
        delay = 1.0
        async with httpx.AsyncClient() as client:
            for attempt in range(retries):
                try:
                    response = await client.post(
                        self.BASE_URL, json=payload, headers=headers, timeout=self.timeout
                    )
                    response.raise_for_status()
                    result = response.json()
                    text = result["choices"][0]["message"]["content"]
                    return text.strip()
                except (httpx.HTTPError, httpx.TimeoutException, asyncio.TimeoutError, KeyError, IndexError) as e:
                    log.warning(f"xAI API request failed on attempt {attempt + 1}: {e}")
                    if attempt == retries - 1:
                        log.error(f"xAI API error: {e}")
                        raise e
                    await asyncio.sleep(delay)
                    delay *= 2.0

        raise RuntimeError("Failed to generate response from xAI API.")


def get_ai_provider(provider_name: Optional[str] = None) -> BaseAIProvider:
    """
    Factory to retrieve an instantiated AI provider based on settings or name.
    Strips brackets from env values (e.g. [key] → key) for safety.
    """
    def _clean(val: str) -> str:
        """Strip surrounding whitespace and bracket wrappers like [value]."""
        val = val.strip()
        if val.startswith("[") and val.endswith("]"):
            val = val[1:-1].strip()
        return val

    provider = provider_name or settings.ai_provider
    provider = _clean(provider).lower()
    api_key  = _clean(settings.api_key)
    model    = _clean(settings.model_name)

    if provider == "gemini":
        if not api_key:
            log.warning("Gemini API key is missing. Falling back to MockAIProvider.")
            return MockAIProvider()
        return GeminiAIProvider(
            api_key=api_key,
            model_name=model or "gemini-1.5-flash",
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
        )
    elif provider in ("openai",):
        if not api_key:
            log.warning("OpenAI API key is missing. Falling back to MockAIProvider.")
            return MockAIProvider()
        return OpenAIProvider(
            api_key=api_key,
            model_name=model or "gpt-3.5-turbo",
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
        )
    elif provider == "anthropic":
        if not api_key:
            log.warning("Anthropic API key is missing. Falling back to MockAIProvider.")
            return MockAIProvider()
        return AnthropicProvider(
            api_key=api_key,
            model_name=model or "claude-3-haiku-20240307",
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
        )
    elif provider in ("xai", "grok", "x"):
        if not api_key:
            log.warning("xAI API key is missing. Falling back to MockAIProvider.")
            return MockAIProvider()
        return XAIProvider(
            api_key=api_key,
            model_name=model or "grok-3-mini",
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
        )
    elif provider in ("ollama", "local"):
        return OllamaAIProvider(
            url=settings.local_llm_url,
            model_name=settings.local_llm_model,
            temperature=settings.temperature,
            max_tokens=settings.max_tokens,
            timeout=settings.timeout,
        )
    else:
        log.warning(f"Unknown AI provider '{provider}'. Falling back to MockAIProvider.")
        return MockAIProvider()

