# ============================================================
# GINI-ORACLE-1 — App Registry
# actions/app_registry.py
# ============================================================
"""
Central registry mapping friendly app names → OS executables.

Windows-first design:
  - Maps "chrome" → "chrome.exe" + common install paths
  - Maps "spotify" → "Spotify.exe"
  - Falls back to shutil.which() for PATH-based apps
  - Supports Linux/macOS as secondary platforms

No hardcoded absolute paths — uses ordered search strategy:
  1. Registry (Windows, via winreg)
  2. Common install directories
  3. PATH lookup (shutil.which)
  4. App Store / Microsoft Store paths
"""

import os
import sys
import shutil
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from utils.logger import get_logger

log = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_LINUX   = sys.platform.startswith("linux")
IS_MAC     = sys.platform == "darwin"


@dataclass
class AppEntry:
    """A registered application with platform-specific metadata."""
    name: str                          # Friendly name e.g. "Chrome"
    aliases: List[str]                 # Recognised spoken names
    process_names: List[str]           # Process names for find/kill
    windows_exe: Optional[str] = None  # Executable name on Windows
    windows_paths: List[str] = field(default_factory=list)  # Common install dirs
    linux_cmd: Optional[str] = None    # Command on Linux
    mac_bundle: Optional[str] = None   # App bundle on macOS
    is_browser: bool = False
    url_scheme: Optional[str] = None   # e.g. "https://" for browsers


# ── App catalogue ─────────────────────────────────────────────

APP_CATALOGUE: List[AppEntry] = [

    # ── Browsers ──────────────────────────────────────────────
    AppEntry(
        name="Chrome",
        aliases=["chrome", "google chrome", "chromium"],
        process_names=["chrome.exe", "google-chrome", "chromium"],
        windows_exe="chrome.exe",
        windows_paths=[
            r"C:\Program Files\Google\Chrome\Application",
            r"C:\Program Files (x86)\Google\Chrome\Application",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application"),
        ],
        linux_cmd="google-chrome",
        mac_bundle="Google Chrome",
        is_browser=True,
        url_scheme="https://",
    ),
    AppEntry(
        name="Firefox",
        aliases=["firefox", "mozilla", "mozilla firefox"],
        process_names=["firefox.exe", "firefox"],
        windows_exe="firefox.exe",
        windows_paths=[
            r"C:\Program Files\Mozilla Firefox",
            r"C:\Program Files (x86)\Mozilla Firefox",
        ],
        linux_cmd="firefox",
        mac_bundle="Firefox",
        is_browser=True,
        url_scheme="https://",
    ),
    AppEntry(
        name="Microsoft Edge",
        aliases=["edge", "microsoft edge", "msedge"],
        process_names=["msedge.exe", "microsoft-edge"],
        windows_exe="msedge.exe",
        windows_paths=[
            r"C:\Program Files (x86)\Microsoft\Edge\Application",
            r"C:\Program Files\Microsoft\Edge\Application",
        ],
        linux_cmd="microsoft-edge",
        mac_bundle="Microsoft Edge",
        is_browser=True,
        url_scheme="https://",
    ),
    AppEntry(
        name="Brave",
        aliases=["brave", "brave browser"],
        process_names=["brave.exe", "brave-browser"],
        windows_exe="brave.exe",
        windows_paths=[
            os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application"),
        ],
        linux_cmd="brave-browser",
        mac_bundle="Brave Browser",
        is_browser=True,
    ),

    # ── Media ─────────────────────────────────────────────────
    AppEntry(
        name="Spotify",
        aliases=["spotify"],
        process_names=["Spotify.exe", "spotify"],
        windows_exe="Spotify.exe",
        windows_paths=[
            os.path.expandvars(r"%APPDATA%\Spotify"),
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps"),
        ],
        linux_cmd="spotify",
        mac_bundle="Spotify",
    ),
    AppEntry(
        name="VLC",
        aliases=["vlc", "vlc media player", "media player"],
        process_names=["vlc.exe", "vlc"],
        windows_exe="vlc.exe",
        windows_paths=[
            r"C:\Program Files\VideoLAN\VLC",
            r"C:\Program Files (x86)\VideoLAN\VLC",
        ],
        linux_cmd="vlc",
        mac_bundle="VLC",
    ),
    AppEntry(
        name="YouTube",
        aliases=["youtube"],
        process_names=["chrome.exe", "msedge.exe", "firefox.exe"],
        windows_exe=None,   # Opens in browser
        linux_cmd=None,
        is_browser=True,
        url_scheme="https://www.youtube.com",
    ),

    # ── Communication ─────────────────────────────────────────
    AppEntry(
        name="WhatsApp",
        aliases=["whatsapp", "whats app"],
        process_names=["WhatsApp.exe", "whatsapp"],
        windows_exe="WhatsApp.exe",
        windows_paths=[
            os.path.expandvars(r"%LOCALAPPDATA%\WhatsApp"),
            os.path.expandvars(r"%APPDATA%\WhatsApp"),
        ],
        linux_cmd="whatsapp-desktop",
        mac_bundle="WhatsApp",
    ),
    AppEntry(
        name="Telegram",
        aliases=["telegram"],
        process_names=["Telegram.exe", "telegram-desktop"],
        windows_exe="Telegram.exe",
        windows_paths=[
            os.path.expandvars(r"%APPDATA%\Telegram Desktop"),
            os.path.expandvars(r"%LOCALAPPDATA%\Telegram Desktop"),
        ],
        linux_cmd="telegram-desktop",
        mac_bundle="Telegram",
    ),
    AppEntry(
        name="Discord",
        aliases=["discord"],
        process_names=["Discord.exe", "discord"],
        windows_exe="Discord.exe",
        windows_paths=[
            os.path.expandvars(r"%LOCALAPPDATA%\Discord"),
        ],
        linux_cmd="discord",
        mac_bundle="Discord",
    ),
    AppEntry(
        name="Zoom",
        aliases=["zoom"],
        process_names=["Zoom.exe", "zoom"],
        windows_exe="Zoom.exe",
        windows_paths=[
            os.path.expandvars(r"%APPDATA%\Zoom\bin"),
        ],
        linux_cmd="zoom",
        mac_bundle="zoom.us",
    ),

    # ── Productivity ──────────────────────────────────────────
    AppEntry(
        name="Notepad",
        aliases=["notepad", "text editor", "note"],
        process_names=["notepad.exe"],
        windows_exe="notepad.exe",
        windows_paths=[r"C:\Windows\System32"],
        linux_cmd="gedit",
        mac_bundle="TextEdit",
    ),
    AppEntry(
        name="Calculator",
        aliases=["calculator", "calc"],
        process_names=["CalculatorApp.exe", "calc.exe", "gnome-calculator"],
        windows_exe="calc.exe",
        windows_paths=[r"C:\Windows\System32"],
        linux_cmd="gnome-calculator",
        mac_bundle="Calculator",
    ),
    AppEntry(
        name="File Manager",
        aliases=["files", "file manager", "explorer", "file explorer"],
        process_names=["explorer.exe", "nautilus", "dolphin"],
        windows_exe="explorer.exe",
        windows_paths=[r"C:\Windows"],
        linux_cmd="nautilus",
        mac_bundle="Finder",
    ),
    AppEntry(
        name="Task Manager",
        aliases=["task manager", "tasks"],
        process_names=["Taskmgr.exe"],
        windows_exe="Taskmgr.exe",
        windows_paths=[r"C:\Windows\System32"],
        linux_cmd="gnome-system-monitor",
        mac_bundle="Activity Monitor",
    ),
    AppEntry(
        name="Settings",
        aliases=["settings", "system settings", "control panel"],
        process_names=["SystemSettings.exe", "ControlPanel"],
        windows_exe="ms-settings:",   # URI scheme for Settings on Windows 10/11
        linux_cmd="gnome-control-center",
        mac_bundle="System Preferences",
    ),

    # ── Dev Tools ─────────────────────────────────────────────
    AppEntry(
        name="VS Code",
        aliases=["vs code", "vscode", "visual studio code", "code"],
        process_names=["Code.exe", "code"],
        windows_exe="Code.exe",
        windows_paths=[
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code"),
            r"C:\Program Files\Microsoft VS Code",
        ],
        linux_cmd="code",
        mac_bundle="Visual Studio Code",
    ),
    AppEntry(
        name="Terminal",
        aliases=["terminal", "command prompt", "cmd", "powershell", "console"],
        process_names=["cmd.exe", "powershell.exe", "WindowsTerminal.exe", "bash"],
        windows_exe="wt.exe",   # Windows Terminal
        windows_paths=[
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps"),
            r"C:\Windows\System32",
        ],
        linux_cmd="x-terminal-emulator",
        mac_bundle="Terminal",
    ),
]


class AppRegistry:
    """
    Looks up app entries by alias and resolves executable paths.
    Platform-aware: returns correct path for Windows/Linux/Mac.
    """

    def __init__(self):
        # Build alias → entry index for fast lookup
        self._index: Dict[str, AppEntry] = {}
        for entry in APP_CATALOGUE:
            for alias in entry.aliases:
                self._index[alias.lower()] = entry
        log.debug(f"AppRegistry loaded: {len(APP_CATALOGUE)} apps, {len(self._index)} aliases")

    def find(self, name: str) -> Optional[AppEntry]:
        """Find an AppEntry by any alias. Returns None if not found."""
        return self._index.get(name.lower().strip())

    def resolve_executable(self, entry: AppEntry) -> Optional[str]:
        """
        Resolve the actual executable path for the current platform.

        Search order (Windows):
          1. shutil.which() — fastest, covers PATH
          2. Common install directories
          3. winreg lookup (HKLM/HKCU App Paths)

        Returns executable path string, or None if not found.
        """
        if IS_WINDOWS:
            return self._resolve_windows(entry)
        elif IS_LINUX:
            return self._resolve_linux(entry)
        elif IS_MAC:
            return self._resolve_mac(entry)
        return None

    def _resolve_windows(self, entry: AppEntry) -> Optional[str]:
        if not entry.windows_exe:
            return None

        # MS Settings URI — special case
        if entry.windows_exe.startswith("ms-"):
            return entry.windows_exe

        # 1. PATH lookup
        found = shutil.which(entry.windows_exe)
        if found:
            return found

        # 2. Common install paths
        for directory in entry.windows_paths:
            candidate = os.path.join(directory, entry.windows_exe)
            if os.path.isfile(candidate):
                return candidate

        # 3. winreg App Paths
        try:
            import winreg
            reg_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{entry.windows_exe}"
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, reg_path) as key:
                        path, _ = winreg.QueryValueEx(key, "")
                        if path and os.path.isfile(path):
                            return path
                except FileNotFoundError:
                    continue
        except ImportError:
            pass

        return None

    def _resolve_linux(self, entry: AppEntry) -> Optional[str]:
        if not entry.linux_cmd:
            return None
        return shutil.which(entry.linux_cmd)

    def _resolve_mac(self, entry: AppEntry) -> Optional[str]:
        if not entry.mac_bundle:
            return None
        path = f"/Applications/{entry.mac_bundle}.app"
        return path if os.path.isdir(path) else None

    def all_aliases(self) -> List[str]:
        return list(self._index.keys())

    def all_apps(self) -> List[str]:
        return [e.name for e in APP_CATALOGUE]


# Singleton
_registry: Optional[AppRegistry] = None

def get_app_registry() -> AppRegistry:
    global _registry
    if _registry is None:
        _registry = AppRegistry()
    return _registry


__all__ = ["AppEntry", "AppRegistry", "get_app_registry", "APP_CATALOGUE"]
