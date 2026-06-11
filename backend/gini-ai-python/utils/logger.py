# ============================================================
# GINI-ORACLE-1 — Centralized Logging System
# utils/logger.py
# Uses loguru when available, falls back to stdlib logging
# ============================================================

import sys
import os
import logging

try:
    from loguru import logger as _loguru_logger
    _USE_LOGURU = True
except ImportError:
    _USE_LOGURU = False

from config.settings import settings


class _StdlibLogger:
    """Stdlib logging wrapper matching loguru's API surface."""
    def __init__(self, name: str = "gini", _extra: dict = None):
        self._log = logging.getLogger(name)
        self._extra = _extra or {}

    def bind(self, **kwargs) -> "_StdlibLogger":
        """Return a new logger with extra context merged in."""
        merged = {**self._extra, **kwargs}
        return _StdlibLogger(self._log.name, _extra=merged)

    def _fmt(self, msg: str) -> str:
        if self._extra:
            ctx = " ".join(f"{k}={v}" for k, v in self._extra.items())
            return f"{msg} [{ctx}]"
        return msg

    def info(self, msg, *a, **kw):    self._log.info(self._fmt(str(msg)))
    def debug(self, msg, *a, **kw):   self._log.debug(self._fmt(str(msg)))
    def warning(self, msg, *a, **kw): self._log.warning(self._fmt(str(msg)))
    def error(self, msg, *a, **kw):   self._log.error(self._fmt(str(msg)))
    def critical(self, msg, *a, **kw):self._log.critical(self._fmt(str(msg)))
    def remove(self): pass
    def add(self, *a, **kw): pass


def _setup_stdlib_logging():
    level = getattr(logging, settings.log_level, logging.INFO)
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    handlers = [logging.StreamHandler(sys.stdout)]

    if settings.log_to_file:
        os.makedirs(os.path.dirname(settings.log_file_path), exist_ok=True)
        handlers.append(logging.FileHandler(settings.log_file_path))

    logging.basicConfig(level=level, format=fmt, handlers=handlers)


def setup_logger():
    if _USE_LOGURU:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        _loguru_logger.remove()
        _loguru_logger.add(
            sys.stdout,
            level=settings.log_level,
            colorize=True,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan> | <level>{message}</level>"
            ),
        )
        if settings.log_to_file:
            os.makedirs(os.path.dirname(settings.log_file_path), exist_ok=True)
            # General log — all levels
            _loguru_logger.add(
                settings.log_file_path,
                level=settings.log_level,
                rotation="10 MB",
                retention="7 days",
                compression="zip",
            )
            # Failures-only log for quick post-mortem
            _failure_log = os.path.join(
                os.path.dirname(settings.log_file_path), "failures.log"
            )
            _loguru_logger.add(
                _failure_log,
                level="WARNING",
                rotation="5 MB",
                retention="30 days",
                compression="zip",
                format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {name} | {message}",
            )
    else:
        _setup_stdlib_logging()


def get_logger(module_name: str):
    """Return a module-specific logger (loguru or stdlib)."""
    if _USE_LOGURU:
        return _loguru_logger.bind(module=module_name)
    return _StdlibLogger(module_name)


# Initialize on import
setup_logger()
logger = _loguru_logger if _USE_LOGURU else _StdlibLogger("gini")

__all__ = ["logger", "get_logger", "setup_logger"]
