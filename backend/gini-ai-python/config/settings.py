# ============================================================
# GINI-ORACLE-1 — Centralized Configuration System
# config/settings.py
# Uses pydantic-settings when available, falls back to os.environ
# ============================================================

import os
from functools import lru_cache
from typing import Literal

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key.upper(), default)

def _env_bool(key: str, default: bool = True) -> bool:
    val = os.environ.get(key.upper(), str(default)).lower()
    return val in ("1", "true", "yes")


try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from pydantic import Field

    class GiniSettings(BaseSettings):
        model_config = SettingsConfigDict(
            env_file=".env", env_file_encoding="utf-8",
            case_sensitive=False, extra="ignore",
        )
        app_name: str = Field(default="GINI-AI")
        app_env: str = Field(default="development")
        app_version: str = Field(default="1.0.0")
        debug: bool = Field(default=True)
        host: str = Field(default="0.0.0.0")
        port: int = Field(default=8000)

        # ── Local LLM (optional, disabled by default) ────────
        # No API keys needed. Enable if you have Ollama running locally.
        local_llm_enabled: bool = Field(default=False)
        local_llm_backend: str = Field(default="ollama")
        local_llm_url: str = Field(default="http://localhost:11434")
        local_llm_model: str = Field(default="qwen2.5")

        # ── AI Provider Settings ──────────────────────────────
        api_key: str = Field(default="")
        model_name: str = Field(default="gemini-1.5-flash")
        temperature: float = Field(default=0.7)
        max_tokens: int = Field(default=1024)
        timeout: float = Field(default=15.0)
        ai_provider: str = Field(default="gemini")

        # ── Voice ─────────────────────────────────────────────
        voice_enabled: bool = Field(default=True)
        voice_language: str = Field(default="en-IN")

        # ── Emotion ───────────────────────────────────────────
        emotion_engine_enabled: bool = Field(default=True)
        emotion_sensitivity: str = Field(default="high")

        # ── Device Control ────────────────────────────────────
        device_control_enabled: bool = Field(default=True)
        smart_home_enabled: bool = Field(default=True)
        hospital_module_enabled: bool = Field(default=True)
        vehicle_module_enabled: bool = Field(default=True)
        mobile_module_enabled: bool = Field(default=True)

        # ── Logging ───────────────────────────────────────────
        log_level: str = Field(default="INFO")
        log_to_file: bool = Field(default=True)
        log_file_path: str = Field(default="logs/gini.log")

        # ── Database ──────────────────────────────────────────
        database_url: str = Field(default="sqlite:///gini.db")
        secret_key: str = Field(default="change_this_in_production")

    @lru_cache()
    def get_settings() -> GiniSettings:
        return GiniSettings()

except ImportError:
    # Fallback: plain dataclass reading from env
    from dataclasses import dataclass

    @dataclass
    class GiniSettings:
        app_name: str = "GINI-AI"
        app_env: str = "development"
        app_version: str = "1.0.0"
        debug: bool = True
        host: str = "0.0.0.0"
        port: int = 8000
        # Local LLM (optional, no API keys)
        local_llm_enabled: bool = False
        local_llm_backend: str = "ollama"
        local_llm_url: str = "http://localhost:11434"
        local_llm_model: str = "qwen2.5"
        # AI Provider Settings
        api_key: str = ""
        model_name: str = "gemini-1.5-flash"
        temperature: float = 0.7
        max_tokens: int = 1024
        timeout: float = 15.0
        ai_provider: str = "gemini"
        voice_enabled: bool = True
        voice_language: str = "en-IN"
        emotion_engine_enabled: bool = True
        emotion_sensitivity: str = "high"
        device_control_enabled: bool = True
        smart_home_enabled: bool = True
        hospital_module_enabled: bool = True
        vehicle_module_enabled: bool = True
        mobile_module_enabled: bool = True
        log_level: str = "INFO"
        log_to_file: bool = False
        log_file_path: str = "logs/gini.log"
        database_url: str = "sqlite:///gini.db"
        secret_key: str = "change_this_in_production"

        @classmethod
        def from_env(cls):
            try:
                temp = float(_env("TEMPERATURE", "0.7"))
            except ValueError:
                temp = 0.7
            try:
                tokens = int(_env("MAX_TOKENS", "1024"))
            except ValueError:
                tokens = 1024
            try:
                tout = float(_env("TIMEOUT", "15.0"))
            except ValueError:
                tout = 15.0
            return cls(
                app_name=_env("APP_NAME", "GINI-AI"),
                app_env=_env("APP_ENV", "development"),
                app_version=_env("APP_VERSION", "1.0.0"),
                debug=_env_bool("DEBUG", True),
                local_llm_enabled=_env_bool("LOCAL_LLM_ENABLED", False),
                local_llm_url=_env("LOCAL_LLM_URL", "http://localhost:11434"),
                local_llm_model=_env("LOCAL_LLM_MODEL", "qwen2.5"),
                log_level=_env("LOG_LEVEL", "INFO"),
                log_to_file=_env_bool("LOG_TO_FILE", False),
                api_key=_env("API_KEY", ""),
                model_name=_env("MODEL_NAME", "gemini-1.5-flash"),
                temperature=temp,
                max_tokens=tokens,
                timeout=tout,
                ai_provider=_env("AI_PROVIDER", "gemini"),
            )

    @lru_cache()
    def get_settings() -> GiniSettings:
        return GiniSettings.from_env()


settings = get_settings()
