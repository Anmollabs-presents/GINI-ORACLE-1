# ============================================================
# GINI-ORACLE-1 — Dependency Validator
# core/dependency_validator.py
# ============================================================
"""
Validates and checks for required dependencies:
  - Python packages (TTS, STT, voice recognition)
  - System binaries (ffmpeg, sox, etc.)
  - System libraries
  - Audio drivers
  - System capabilities

Provides:
  - Import testing with graceful failures
  - Binary existence checking
  - Version validation
  - Degradation suggestions
  - Self-healing recommendations
"""

import sys
import subprocess
import importlib
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from enum import Enum

from utils.logger import get_logger

log = get_logger(__name__)


class DependencyStatus(str, Enum):
    """Status of a dependency."""
    INSTALLED = "installed"
    MISSING = "missing"
    WRONG_VERSION = "wrong_version"
    ERROR = "error"


@dataclass
class DependencyCheck:
    """Result of a dependency check."""
    name: str
    status: DependencyStatus
    version: Optional[str] = None
    message: str = ""
    is_critical: bool = False
    fallback: Optional[str] = None


class DependencyValidator:
    """Validates system dependencies."""

    def __init__(self):
        self.checks: List[DependencyCheck] = []
        self.is_healthy = True

        # Define required and optional dependencies
        self.critical_packages = [
            "fastapi",
            "uvicorn",
            "pydantic",
            "sqlalchemy",
        ]

        self.optional_packages = {
            "tts": ["pyttsx3", "gtts", "espeak"],
            "stt": ["vosk", "openai", "google-cloud-speech"],
            "voice": ["pyaudio", "numpy", "librosa"],
            "browser": ["selenium", "playwright"],
        }

        self.required_binaries = {
            "python": "Python interpreter",
        }

        self.optional_binaries = {
            "ffmpeg": "Audio/video processing",
            "sox": "Sound eXchange audio tool",
            "espeak": "Text-to-speech engine",
        }

        log.info("🔍 DependencyValidator initialized")

    # ── Package Checking ──────────────────────────────────────

    async def check_all_dependencies(self) -> Dict[str, List[DependencyCheck]]:
        """Run all dependency checks."""
        log.info("🔍 Checking all dependencies...")

        self.checks = []
        self.is_healthy = True

        results = {
            "critical_packages": await self._check_critical_packages(),
            "optional_packages": await self._check_optional_packages(),
            "binaries": await self._check_binaries(),
            "system_capabilities": await self._check_system_capabilities(),
        }

        # Determine overall health
        critical_fails = [
            c for group in results.values()
            for c in group
            if c.is_critical and c.status == DependencyStatus.MISSING
        ]

        if critical_fails:
            self.is_healthy = False
            log.error(f"❌ {len(critical_fails)} critical dependencies missing")
        else:
            log.info("✅ All critical dependencies present")

        self.checks.extend([c for group in results.values() for c in group])
        return results

    async def _check_critical_packages(self) -> List[DependencyCheck]:
        """Check critical packages required for core functionality."""
        results = []

        for package in self.critical_packages:
            check = await self._check_package(package, critical=True)
            results.append(check)

        return results

    async def _check_optional_packages(self) -> List[DependencyCheck]:
        """Check optional packages for extended functionality."""
        results = []

        for category, packages in self.optional_packages.items():
            # Check if at least one package in category is available
            found = False
            for package in packages:
                check = await self._check_package(package, critical=False)
                results.append(check)
                if check.status == DependencyStatus.INSTALLED:
                    found = True
                    break

            if not found:
                log.warning(
                    f"⚠️  No {category} package found. "
                    f"Install one of: {', '.join(packages)}"
                )

        return results

    async def _check_package(self, package_name: str, critical: bool = False) -> DependencyCheck:
        """Check if a Python package is installed."""
        # Map install names → importable module names
        _import_name = {
            "openai-whisper": "whisper",
            "google-cloud-speech": "google.cloud.speech",
            "pycaw": "pycaw.pycaw",
        }
        import_name = _import_name.get(package_name, package_name)

        try:
            module = importlib.import_module(import_name)
            version = getattr(module, "__version__", "installed")
            return DependencyCheck(
                name=package_name,
                status=DependencyStatus.INSTALLED,
                version=version,
                message=f"✅ {package_name} {version}",
            )
        except ImportError:
            return DependencyCheck(
                name=package_name,
                status=DependencyStatus.MISSING,
                message=f"Package not installed: {package_name}",
                is_critical=critical,
                fallback=self._get_install_command(package_name),
            )
        except Exception as e:
            log.error(f"Error checking {package_name}: {e}")
            return DependencyCheck(
                name=package_name,
                status=DependencyStatus.ERROR,
                message=f"Error checking package: {str(e)[:50]}",
                is_critical=critical,
            )

    # ── Binary Checking ───────────────────────────────────────

    async def _check_binaries(self) -> List[DependencyCheck]:
        """Check for required system binaries."""
        results = []

        for binary, description in self.required_binaries.items():
            check = await self._check_binary(binary, description, critical=True)
            results.append(check)

        for binary, description in self.optional_binaries.items():
            check = await self._check_binary(binary, description, critical=False)
            results.append(check)

        return results

    async def _check_binary(
        self,
        binary: str,
        description: str,
        critical: bool = False,
    ) -> DependencyCheck:
        """Check if a system binary is available."""
        import shutil

        path = shutil.which(binary)
        if path:
            try:
                result = subprocess.run(
                    [binary, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version = result.stdout.split("\n")[0][:50] if result.returncode == 0 else "unknown"
                return DependencyCheck(
                    name=binary,
                    status=DependencyStatus.INSTALLED,
                    version=version,
                    message=f"✅ {binary} available at {path}",
                )
            except Exception as e:
                log.warning(f"Could not get version for {binary}: {e}")
                return DependencyCheck(
                    name=binary,
                    status=DependencyStatus.INSTALLED,
                    message=f"✅ {binary} available",
                )
        else:
            return DependencyCheck(
                name=binary,
                status=DependencyStatus.MISSING,
                message=f"{description} not found in PATH",
                is_critical=critical,
                fallback=self._get_install_suggestion(binary),
            )

    # ── System Capabilities ───────────────────────────────────

    async def _check_system_capabilities(self) -> List[DependencyCheck]:
        """Check system capabilities."""
        results = []

        # Check for audio support
        audio_check = await self._check_audio_support()
        results.append(audio_check)

        # Check for display/GUI support
        display_check = await self._check_display_support()
        results.append(display_check)

        return results

    async def _check_audio_support(self) -> DependencyCheck:
        """Check if system has audio support."""
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            device_count = pa.get_device_count()
            pa.terminate()

            if device_count > 0:
                return DependencyCheck(
                    name="audio_support",
                    status=DependencyStatus.INSTALLED,
                    message=f"✅ Audio support ({device_count} devices found)",
                )
            else:
                return DependencyCheck(
                    name="audio_support",
                    status=DependencyStatus.MISSING,
                    message="No audio devices detected",
                    is_critical=False,
                )
        except Exception as e:
            return DependencyCheck(
                name="audio_support",
                status=DependencyStatus.ERROR,
                message=f"Could not check audio support: {str(e)[:50]}",
                is_critical=False,
            )

    async def _check_display_support(self) -> DependencyCheck:
        """Check if system has display support."""
        if sys.platform == "win32":
            return DependencyCheck(
                name="display_support",
                status=DependencyStatus.INSTALLED,
                message="✅ Display support (Windows)",
            )
        elif sys.platform == "darwin":
            return DependencyCheck(
                name="display_support",
                status=DependencyStatus.INSTALLED,
                message="✅ Display support (macOS)",
            )
        else:
            # Linux - check for DISPLAY
            import os
            if "DISPLAY" in os.environ or "WAYLAND_DISPLAY" in os.environ:
                return DependencyCheck(
                    name="display_support",
                    status=DependencyStatus.INSTALLED,
                    message="✅ Display support (X11/Wayland)",
                )
            else:
                return DependencyCheck(
                    name="display_support",
                    status=DependencyStatus.MISSING,
                    message="No display server found (headless mode)",
                    is_critical=False,
                )

    # ── Helper Methods ────────────────────────────────────────

    def _get_install_command(self, package: str) -> str:
        """Get pip install command for package."""
        return f"pip install {package}"

    def _get_install_suggestion(self, binary: str) -> str:
        """Get installation suggestion for binary."""
        suggestions = {
            "ffmpeg": "sudo apt-get install ffmpeg  (Linux) or brew install ffmpeg (macOS)",
            "sox": "sudo apt-get install sox  (Linux) or brew install sox (macOS)",
            "espeak": "sudo apt-get install espeak  (Linux) or brew install espeak (macOS)",
        }
        return suggestions.get(binary, f"Install {binary} via package manager")

    # ── Reporting ──────────────────────────────────────────────

    def get_report(self) -> dict:
        """Get comprehensive dependency report."""
        return {
            "healthy": self.is_healthy,
            "total_checks": len(self.checks),
            "installed": sum(1 for c in self.checks if c.status == DependencyStatus.INSTALLED),
            "missing": sum(1 for c in self.checks if c.status == DependencyStatus.MISSING),
            "errors": sum(1 for c in self.checks if c.status == DependencyStatus.ERROR),
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "version": c.version,
                    "message": c.message,
                    "critical": c.is_critical,
                    "fallback": c.fallback,
                }
                for c in self.checks
            ]
        }

    async def get_recommendations(self) -> List[str]:
        """Get recommendations for missing dependencies."""
        recommendations = []

        for check in self.checks:
            if check.status == DependencyStatus.MISSING and check.fallback:
                recommendations.append(f"{check.name}: {check.fallback}")

        return recommendations


# ── Global instance ──────────────────────────────────────

_validator: Optional[DependencyValidator] = None


def get_dependency_validator() -> DependencyValidator:
    """Get or create global dependency validator."""
    global _validator
    if _validator is None:
        _validator = DependencyValidator()
    return _validator


__all__ = [
    "DependencyValidator",
    "DependencyStatus",
    "DependencyCheck",
    "get_dependency_validator",
]
