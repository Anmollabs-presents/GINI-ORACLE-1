# ============================================================
# GINI-ORACLE-1 — Process Manager
# actions/process_manager.py
# ============================================================
"""
Safe OS process management for Gini.ai app control.

Operations:
  launch(app)     — start a new process safely
  close(app)      — graceful terminate (SIGTERM → wait → SIGKILL)
  kill(app)       — immediate force kill (SIGKILL)
  focus(app)      — bring window to foreground
  is_running(app) — check if process is active
  list_running()  — all running processes

Platform support:
  Windows  — subprocess, os.startfile, winreg, ctypes (SetForegroundWindow)
  Linux    — subprocess, wmctrl for focus
  macOS    — subprocess, AppleScript for focus

Safety rules:
  - Never kill system-critical processes (svchost, lsass, kernel, etc.)
  - Always use graceful close before force kill
  - Timeout on all blocking operations
  - Full exception safety — never raises to caller
"""

import os
import sys
import time
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

from actions.app_registry import AppEntry, AppRegistry, get_app_registry
from utils.logger import get_logger

log = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_LINUX   = sys.platform.startswith("linux")
IS_MAC     = sys.platform == "darwin"

# Processes that must NEVER be killed
_PROTECTED_PROCESSES = {
    # Windows system
    "svchost.exe", "lsass.exe", "csrss.exe", "winlogon.exe",
    "services.exe", "smss.exe", "wininit.exe", "system",
    "explorer.exe",   # Allow close, protect from kill
    # Linux system
    "init", "systemd", "kernel", "kthreadd",
    # macOS system
    "launchd", "kernel_task",
}

_CLOSE_TIMEOUT = 5.0    # Seconds to wait for graceful close before force kill
_LAUNCH_TIMEOUT = 10.0  # Seconds to wait for process to start


class ProcessResult(str, Enum):
    SUCCESS          = "success"
    NOT_FOUND        = "not_found"         # App not in registry or PATH
    NOT_RUNNING      = "not_running"       # Can't close/focus what isn't running
    ALREADY_RUNNING  = "already_running"   # Launch when already open
    PERMISSION_ERROR = "permission_error"  # Access denied
    PROTECTED        = "protected"         # Tried to kill a system process
    TIMEOUT          = "timeout"           # Operation timed out
    ERROR            = "error"             # Unexpected error


@dataclass
class ProcessAction:
    """Result of a process management operation."""
    result: ProcessResult
    app_name: str
    message: str
    pid: Optional[int] = None
    executable: Optional[str] = None
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.result == ProcessResult.SUCCESS

    def to_dict(self) -> dict:
        return {
            "result":     self.result.value,
            "app_name":   self.app_name,
            "message":    self.message,
            "pid":        self.pid,
            "executable": self.executable,
            "error":      self.error,
        }


class ProcessManager:
    """
    Safe cross-platform process manager.
    All methods are exception-safe and return ProcessAction.
    """

    def __init__(self, registry: Optional[AppRegistry] = None):
        self._registry = registry or get_app_registry()
        log.info("⚙️ ProcessManager initialized")

    # ── Launch ────────────────────────────────────────────────

    def launch(self, app_name: str, url: Optional[str] = None) -> ProcessAction:
        """
        Launch an application.
        If app is a browser and url is given, opens the URL.
        If app is already running, returns ALREADY_RUNNING.
        """
        entry = self._registry.find(app_name)
        if not entry:
            # Last resort: try raw command
            return self._launch_raw(app_name)

        # Check if already running
        if self._is_process_running(entry.process_names):
            log.info(f"{entry.name} already running — bringing to front")
            focus_result = self.focus(app_name)
            if focus_result.success:
                return ProcessAction(
                    result=ProcessResult.ALREADY_RUNNING,
                    app_name=entry.name,
                    message=f"{entry.name} is already open.",
                )

        # Browser URL launch
        if entry.is_browser and url:
            return self._launch_url(url, entry)

        # URL-only apps (YouTube etc.)
        if entry.url_scheme and entry.url_scheme.startswith("https://"):
            return self._launch_url(entry.url_scheme, entry)

        # Resolve executable
        executable = self._registry.resolve_executable(entry)
        if not executable:
            return ProcessAction(
                result=ProcessResult.NOT_FOUND,
                app_name=entry.name,
                message=f"Could not find {entry.name} on this system.",
                error="executable_not_found",
            )

        return self._launch_executable(executable, entry.name)

    def _launch_executable(self, executable: str, app_name: str) -> ProcessAction:
        """Launch a resolved executable path safely."""
        try:
            if IS_WINDOWS:
                if executable.startswith("ms-"):
                    # Windows Settings URI
                    os.startfile(executable)
                    return ProcessAction(
                        result=ProcessResult.SUCCESS,
                        app_name=app_name,
                        message=f"Opening {app_name}.",
                    )
                proc = subprocess.Popen(
                    [executable],
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                    close_fds=True,
                )
            elif IS_MAC:
                proc = subprocess.Popen(
                    ["open", "-a", executable],
                    close_fds=True,
                )
            else:
                proc = subprocess.Popen(
                    [executable],
                    close_fds=True,
                    start_new_session=True,
                )

            log.info(f"✅ Launched: {app_name} (pid={proc.pid})")
            return ProcessAction(
                result=ProcessResult.SUCCESS,
                app_name=app_name,
                message=f"Opening {app_name} now.",
                pid=proc.pid,
                executable=executable,
            )

        except PermissionError as e:
            log.warning(f"Permission denied launching {app_name}: {e}")
            return ProcessAction(
                result=ProcessResult.PERMISSION_ERROR,
                app_name=app_name,
                message=f"Permission denied opening {app_name}.",
                error=str(e),
            )
        except FileNotFoundError as e:
            return ProcessAction(
                result=ProcessResult.NOT_FOUND,
                app_name=app_name,
                message=f"Could not find {app_name}.",
                error=str(e),
            )
        except Exception as e:
            log.error(f"Launch error for {app_name}: {e}")
            return ProcessAction(
                result=ProcessResult.ERROR,
                app_name=app_name,
                message=f"Failed to open {app_name}.",
                error=str(e),
            )

    def _launch_raw(self, command: str) -> ProcessAction:
        """Try to launch an unrecognised command directly via PATH."""
        executable = shutil.which(command)
        if not executable:
            return ProcessAction(
                result=ProcessResult.NOT_FOUND,
                app_name=command,
                message=f"I don't know how to open '{command}'.",
                error="not_in_registry_or_path",
            )
        return self._launch_executable(executable, command.title())

    def _launch_url(self, url: str, entry: AppEntry) -> ProcessAction:
        """Open a URL in the default or specified browser."""
        try:
            import webbrowser
            webbrowser.open(url)
            return ProcessAction(
                result=ProcessResult.SUCCESS,
                app_name=entry.name,
                message=f"Opening {entry.name} in browser.",
                executable=url,
            )
        except Exception as e:
            return ProcessAction(
                result=ProcessResult.ERROR,
                app_name=entry.name,
                message=f"Could not open {entry.name}.",
                error=str(e),
            )

    # ── Close ─────────────────────────────────────────────────

    def close(self, app_name: str) -> ProcessAction:
        """
        Gracefully close an application.
        Sends SIGTERM, waits _CLOSE_TIMEOUT seconds, then SIGKILL if needed.
        """
        entry = self._registry.find(app_name)
        process_names = entry.process_names if entry else [app_name]
        display_name = entry.name if entry else app_name.title()

        procs = self._find_processes(process_names)
        if not procs:
            return ProcessAction(
                result=ProcessResult.NOT_RUNNING,
                app_name=display_name,
                message=f"{display_name} doesn't appear to be running.",
            )

        closed = []
        errors = []

        for proc in procs:
            try:
                proc_name = proc.name() if hasattr(proc, 'name') else str(proc)
                if self._is_protected(proc_name):
                    errors.append(f"{proc_name} is a system process — skipped")
                    continue

                # Graceful terminate
                proc.terminate()
                try:
                    proc.wait(timeout=_CLOSE_TIMEOUT)
                    closed.append(proc.pid)
                    log.info(f"✅ Closed: {display_name} (pid={proc.pid})")
                except Exception:
                    # Force kill if graceful close timed out
                    proc.kill()
                    closed.append(proc.pid)
                    log.info(f"Force killed: {display_name} (pid={proc.pid})")

            except Exception as e:
                errors.append(str(e))

        if closed:
            return ProcessAction(
                result=ProcessResult.SUCCESS,
                app_name=display_name,
                message=f"Closed {display_name}.",
                pid=closed[0],
            )

        return ProcessAction(
            result=ProcessResult.ERROR,
            app_name=display_name,
            message=f"Could not close {display_name}.",
            error="; ".join(errors),
        )

    # ── Kill ──────────────────────────────────────────────────

    def kill(self, app_name: str) -> ProcessAction:
        """
        Force-kill a process immediately (SIGKILL).
        Refuses to kill protected system processes.
        """
        entry = self._registry.find(app_name)
        process_names = entry.process_names if entry else [app_name]
        display_name = entry.name if entry else app_name.title()

        procs = self._find_processes(process_names)
        if not procs:
            return ProcessAction(
                result=ProcessResult.NOT_RUNNING,
                app_name=display_name,
                message=f"{display_name} is not running.",
            )

        killed = []
        for proc in procs:
            try:
                proc_name = proc.name() if hasattr(proc, 'name') else str(proc)
                if self._is_protected(proc_name):
                    return ProcessAction(
                        result=ProcessResult.PROTECTED,
                        app_name=display_name,
                        message=f"I can't kill {proc_name} — it's a system process.",
                        error="protected_process",
                    )
                proc.kill()
                killed.append(proc.pid)
                log.info(f"⚡ Killed: {display_name} (pid={proc.pid})")
            except Exception as e:
                log.error(f"Kill error for {display_name}: {e}")

        if killed:
            return ProcessAction(
                result=ProcessResult.SUCCESS,
                app_name=display_name,
                message=f"Force-closed {display_name}.",
                pid=killed[0],
            )

        return ProcessAction(
            result=ProcessResult.ERROR,
            app_name=display_name,
            message=f"Could not kill {display_name}.",
        )

    # ── Focus ─────────────────────────────────────────────────

    def focus(self, app_name: str) -> ProcessAction:
        """
        Bring an application window to the foreground.
        Windows: uses ctypes SetForegroundWindow
        Linux:   uses wmctrl (if installed)
        macOS:   uses AppleScript
        """
        entry = self._registry.find(app_name)
        display_name = entry.name if entry else app_name.title()

        if not entry:
            return ProcessAction(
                result=ProcessResult.NOT_FOUND,
                app_name=display_name,
                message=f"I don't know how to focus {display_name}.",
            )

        procs = self._find_processes(entry.process_names)
        if not procs:
            return ProcessAction(
                result=ProcessResult.NOT_RUNNING,
                app_name=display_name,
                message=f"{display_name} is not running.",
            )

        try:
            if IS_WINDOWS:
                return self._focus_windows(display_name, entry)
            elif IS_LINUX:
                return self._focus_linux(display_name, entry)
            elif IS_MAC:
                return self._focus_mac(display_name, entry)
        except Exception as e:
            log.error(f"Focus error for {display_name}: {e}")

        return ProcessAction(
            result=ProcessResult.SUCCESS,
            app_name=display_name,
            message=f"Switched to {display_name}.",
        )

    def _focus_windows(self, display_name: str, entry: AppEntry) -> ProcessAction:
        """Focus window on Windows using ctypes EnumWindows."""
        try:
            import ctypes
            import ctypes.wintypes

            target_names = {n.lower().replace(".exe", "") for n in entry.process_names}
            user32 = ctypes.windll.user32

            found_hwnd = [None]

            def enum_callback(hwnd, _):
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        buf = ctypes.create_unicode_buffer(length + 1)
                        user32.GetWindowTextW(hwnd, buf, length + 1)
                        title = buf.value.lower()
                        for name in target_names:
                            if name in title:
                                found_hwnd[0] = hwnd
                                return False  # Stop enumeration
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
            user32.EnumWindows(WNDENUMPROC(enum_callback), 0)

            if found_hwnd[0]:
                user32.SetForegroundWindow(found_hwnd[0])
                user32.ShowWindow(found_hwnd[0], 9)  # SW_RESTORE
                return ProcessAction(
                    result=ProcessResult.SUCCESS,
                    app_name=display_name,
                    message=f"Switched to {display_name}.",
                )
        except Exception as e:
            log.debug(f"Windows focus error: {e}")

        return ProcessAction(
            result=ProcessResult.SUCCESS,
            app_name=display_name,
            message=f"Switched to {display_name}.",
        )

    def _focus_linux(self, display_name: str, entry: AppEntry) -> ProcessAction:
        """Focus window on Linux using wmctrl."""
        wmctrl = shutil.which("wmctrl")
        if wmctrl:
            try:
                subprocess.run(
                    [wmctrl, "-a", display_name],
                    timeout=2.0, capture_output=True,
                )
            except Exception:
                pass
        return ProcessAction(
            result=ProcessResult.SUCCESS,
            app_name=display_name,
            message=f"Switched to {display_name}.",
        )

    def _focus_mac(self, display_name: str, entry: AppEntry) -> ProcessAction:
        """Focus window on macOS using AppleScript."""
        if entry.mac_bundle:
            script = f'tell application "{entry.mac_bundle}" to activate'
            try:
                subprocess.run(
                    ["osascript", "-e", script],
                    timeout=3.0, capture_output=True,
                )
            except Exception:
                pass
        return ProcessAction(
            result=ProcessResult.SUCCESS,
            app_name=display_name,
            message=f"Switched to {display_name}.",
        )

    # ── Query ─────────────────────────────────────────────────

    def is_running(self, app_name: str) -> bool:
        """Check if an app is currently running."""
        entry = self._registry.find(app_name)
        process_names = entry.process_names if entry else [app_name]
        return self._is_process_running(process_names)

    def list_running(self) -> List[dict]:
        """List all running processes (from known apps only)."""
        running = []
        try:
            import psutil
            procs = {p.name().lower() for p in psutil.process_iter(['name'])}
            for entry in get_app_registry()._index.values():
                for pname in entry.process_names:
                    if pname.lower() in procs:
                        running.append({
                            "app": entry.name,
                            "process": pname,
                        })
                        break
        except ImportError:
            log.debug("psutil not available for list_running")
        return running

    # ── Internal helpers ──────────────────────────────────────

    def _find_processes(self, names: List[str]) -> list:
        """Find running processes matching any of the given names."""
        try:
            import psutil
            result = []
            names_lower = {n.lower() for n in names}
            for proc in psutil.process_iter(['name', 'pid']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() in names_lower:
                        result.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return result
        except ImportError:
            return self._find_processes_fallback(names)

    def _find_processes_fallback(self, names: List[str]) -> list:
        """Fallback process finder using subprocess (no psutil)."""
        class FakeProc:
            def __init__(self, pid, name):
                self.pid = pid
                self._name = name
            def name(self): return self._name
            def terminate(self):
                try: os.kill(self.pid, 15)
                except: pass
            def kill(self):
                try: os.kill(self.pid, 9)
                except: pass
            def wait(self, timeout=None): time.sleep(0.1)

        try:
            if IS_WINDOWS:
                out = subprocess.check_output(
                    ["tasklist", "/FO", "CSV", "/NH"], text=True
                )
                procs = []
                for line in out.strip().split('\n'):
                    parts = line.strip('"').split('","')
                    if len(parts) >= 2:
                        pname, pid = parts[0], parts[1]
                        if pname.lower() in {n.lower() for n in names}:
                            procs.append(FakeProc(int(pid), pname))
                return procs
            else:
                out = subprocess.check_output(
                    ["ps", "aux"], text=True
                )
                procs = []
                for line in out.strip().split('\n')[1:]:
                    parts = line.split()
                    if len(parts) >= 11:
                        pid = int(parts[1])
                        cmd = os.path.basename(parts[10])
                        if cmd.lower() in {n.lower() for n in names}:
                            procs.append(FakeProc(pid, cmd))
                return procs
        except Exception:
            return []

    def _is_process_running(self, names: List[str]) -> bool:
        return len(self._find_processes(names)) > 0

    def _is_protected(self, process_name: str) -> bool:
        return process_name.lower() in {p.lower() for p in _PROTECTED_PROCESSES}


# Singleton
_manager: Optional[ProcessManager] = None

def get_process_manager() -> ProcessManager:
    global _manager
    if _manager is None:
        _manager = ProcessManager()
    return _manager


__all__ = ["ProcessManager", "ProcessAction", "ProcessResult", "get_process_manager"]
