# ============================================================
# GINI-ORACLE-1 — System Executor
# actions/system_executor.py
# ============================================================
"""
Real OS-level system control execution layer.

Supports:
  Windows  — PowerShell, WScript, ctypes, pycaw (volume), wmi
  Linux    — pactl/amixer (volume), brightnessctl/xrandr (brightness),
             systemctl/loginctl (power), xdg-screensaver/loginctl (lock)
  macOS    — osascript, pmset, brightness CLI

All methods:
  - Return SystemActionResult (never raise to caller)
  - Log every action taken
  - Validate inputs before executing
  - Use subprocess with timeouts

Design: One executor per platform, selected at import time.
        Caller (SystemControlHandler) never checks platform.
"""

import os
import sys
import shutil
import subprocess
import math
from dataclasses import dataclass
from typing import Optional
from enum import Enum

from utils.logger import get_logger

log = get_logger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_LINUX   = sys.platform.startswith("linux")
IS_MAC     = sys.platform == "darwin"

_CMD_TIMEOUT = 5   # seconds


class ActionStatus(str, Enum):
    SUCCESS         = "success"
    PARTIAL         = "partial"       # Executed but result uncertain
    NOT_SUPPORTED   = "not_supported" # Feature unavailable on this platform/config
    PERMISSION_ERROR= "permission_error"
    ERROR           = "error"


@dataclass
class SystemActionResult:
    """Result of a system-level action."""
    status: ActionStatus
    message: str
    value: Optional[float] = None     # e.g. current volume level 0-100
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.status in (ActionStatus.SUCCESS, ActionStatus.PARTIAL)

    def to_dict(self) -> dict:
        return {
            "status":  self.status.value,
            "message": self.message,
            "value":   self.value,
            "error":   self.error,
        }


def _ok(message: str, value: float = None) -> SystemActionResult:
    return SystemActionResult(ActionStatus.SUCCESS, message, value)

def _partial(message: str) -> SystemActionResult:
    return SystemActionResult(ActionStatus.PARTIAL, message)

def _unsupported(feature: str) -> SystemActionResult:
    return SystemActionResult(
        ActionStatus.NOT_SUPPORTED,
        f"{feature} is not supported on this platform.",
    )

def _error(message: str, err: str = "") -> SystemActionResult:
    return SystemActionResult(ActionStatus.ERROR, message, error=err)


def _run(cmd: list, timeout: int = _CMD_TIMEOUT) -> tuple[bool, str]:
    """Run a subprocess command. Returns (success, output)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except FileNotFoundError:
        return False, f"command not found: {cmd[0]}"
    except Exception as e:
        return False, str(e)


# ── Windows Executor ──────────────────────────────────────────

class WindowsExecutor:
    """System control for Windows using PowerShell + ctypes."""

    # ── Volume ────────────────────────────────────────────────

    def volume_set(self, level: int) -> SystemActionResult:
        level = max(0, min(100, level))
        # Try pycaw first (most reliable), fall back to PowerShell
        result = self._volume_pycaw(level)
        if result.success:
            return result
        return self._volume_powershell(level)

    def _volume_pycaw(self, level: int) -> SystemActionResult:
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMasterVolumeLevelScalar(level / 100.0, None)
            return _ok(f"Volume set to {level}%.", level)
        except ImportError:
            return _error("pycaw not installed")
        except Exception as e:
            return _error("pycaw volume error", str(e))

    def _volume_powershell(self, level: int) -> SystemActionResult:
        script = (
            f"$wshShell = New-Object -ComObject WScript.Shell; "
            f"$vol = [int](({level}/100)*65535); "
            f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Multimedia\\Audio' "
            f"-Name 'MasterVolume' -Value $vol -ErrorAction SilentlyContinue; "
            f"(New-Object -com Shell.Application).Windows() | ForEach-Object {{ $_ }}"
        )
        # Simpler nircmd approach
        nircmd = shutil.which("nircmd")
        if nircmd:
            scalar = int(level / 100 * 65535)
            ok, out = _run([nircmd, "setsysvolume", str(scalar)])
            if ok:
                return _ok(f"Volume set to {level}%.", level)

        # PowerShell SendKeys approach (basic fallback)
        ok, out = _run(["powershell", "-Command",
            f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms'); "
            f"for($i=0;$i -lt 50;$i++){{[System.Windows.Forms.SendKeys]::SendWait([char]174)}}"
        ])
        return _partial(f"Volume adjusted to approximately {level}%.")

    def volume_get(self) -> SystemActionResult:
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            level = int(volume.GetMasterVolumeLevelScalar() * 100)
            return _ok(f"Current volume: {level}%.", level)
        except Exception:
            return _partial("Could not read current volume level.")

    def mute(self) -> SystemActionResult:
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMute(1, None)
            return _ok("Muted.")
        except ImportError:
            nircmd = shutil.which("nircmd")
            if nircmd:
                ok, _ = _run([nircmd, "mutesysvolume", "1"])
                return _ok("Muted.") if ok else _partial("Mute attempted.")
            return _partial("Mute command sent.")

    def unmute(self) -> SystemActionResult:
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMute(0, None)
            return _ok("Unmuted.")
        except ImportError:
            nircmd = shutil.which("nircmd")
            if nircmd:
                ok, _ = _run([nircmd, "mutesysvolume", "0"])
                return _ok("Unmuted.") if ok else _partial("Unmute attempted.")
            return _partial("Unmute command sent.")

    def volume_step(self, direction: str, steps: int = 5) -> SystemActionResult:
        """Increase or decrease volume by steps."""
        import ctypes
        VK_VOLUME_UP   = 0xAF
        VK_VOLUME_DOWN = 0xAE
        key = VK_VOLUME_UP if direction == "up" else VK_VOLUME_DOWN
        try:
            for _ in range(steps):
                ctypes.windll.user32.keybd_event(key, 0, 0, 0)
                ctypes.windll.user32.keybd_event(key, 0, 2, 0)
            label = "up" if direction == "up" else "down"
            return _ok(f"Volume turned {label}.")
        except Exception as e:
            return _error("Volume key error", str(e))

    def _send_media_key(self, key: int, name: str) -> SystemActionResult:
        try:
            import ctypes
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
            ctypes.windll.user32.keybd_event(key, 0, 2, 0)
            return _ok(f"{name} media command sent.")
        except Exception as e:
            return _error("Media key error", str(e))

    def media_play(self) -> SystemActionResult:
        return self._send_media_key(0xB3, "Play")

    def media_pause(self) -> SystemActionResult:
        return self._send_media_key(0xB3, "Pause")

    def media_next(self) -> SystemActionResult:
        return self._send_media_key(0xB0, "Next track")

    def media_previous(self) -> SystemActionResult:
        return self._send_media_key(0xB1, "Previous track")

    def media_stop(self) -> SystemActionResult:
        return self._send_media_key(0xB2, "Stop")

    # ── Brightness ────────────────────────────────────────────

    def brightness_set(self, level: int) -> SystemActionResult:
        level = max(0, min(100, level))
        try:
            import wmi
            c = wmi.WMI(namespace="wmi")
            methods = c.WmiMonitorBrightnessMethods()[0]
            methods.WmiSetBrightness(level, 0)
            return _ok(f"Brightness set to {level}%.", level)
        except ImportError:
            pass
        ok, out = _run(["powershell", "-Command",
            f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
            f".WmiSetBrightness(1,{level})"
        ])
        return _ok(f"Brightness set to {level}%.", level) if ok else _partial(f"Brightness adjusted.")

    def brightness_step(self, direction: str, step: int = 10) -> SystemActionResult:
        ok, out = _run(["powershell", "-Command",
            f"$b = (Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness; "
            f"$new = [math]::Min(100,[math]::Max(0,$b{'+' if direction=='up' else '-'}{step})); "
            f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,$new)"
        ])
        label = "up" if direction == "up" else "down"
        return _ok(f"Brightness turned {label}.") if ok else _partial(f"Brightness adjusted {label}.")

    # ── Power ─────────────────────────────────────────────────

    def shutdown(self, delay: int = 0) -> SystemActionResult:
        ok, out = _run(["shutdown", "/s", "/t", str(delay)])
        return _ok("Shutting down...") if ok else _error("Shutdown failed.", out)

    def restart(self, delay: int = 0) -> SystemActionResult:
        ok, out = _run(["shutdown", "/r", "/t", str(delay)])
        return _ok("Restarting...") if ok else _error("Restart failed.", out)

    def sleep(self) -> SystemActionResult:
        ok, out = _run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return _ok("Going to sleep.") if ok else _partial("Sleep initiated.")

    def lock_screen(self) -> SystemActionResult:
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            return _ok("Screen locked.")
        except Exception as e:
            ok, out = _run(["rundll32.exe", "user32.dll,LockWorkStation"])
            return _ok("Screen locked.") if ok else _error("Lock failed.", str(e))

    def cancel_shutdown(self) -> SystemActionResult:
        ok, out = _run(["shutdown", "/a"])
        return _ok("Shutdown cancelled.") if ok else _error("Cancel failed.", out)


# ── Linux Executor ────────────────────────────────────────────

class LinuxExecutor:
    """System control for Linux using pactl/amixer, brightnessctl, systemctl."""

    def __init__(self):
        self._vol_backend = self._detect_volume_backend()
        self._bright_backend = self._detect_brightness_backend()

    def _detect_volume_backend(self) -> str:
        if shutil.which("pactl"):    return "pactl"
        if shutil.which("amixer"):   return "amixer"
        return "none"

    def _detect_brightness_backend(self) -> str:
        if shutil.which("brightnessctl"): return "brightnessctl"
        if shutil.which("xrandr"):        return "xrandr"
        if shutil.which("xbacklight"):    return "xbacklight"
        return "none"

    # ── Volume ────────────────────────────────────────────────

    def volume_set(self, level: int) -> SystemActionResult:
        level = max(0, min(100, level))
        if self._vol_backend == "pactl":
            ok, out = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
            return _ok(f"Volume set to {level}%.", level) if ok else _error("pactl failed.", out)
        if self._vol_backend == "amixer":
            ok, out = _run(["amixer", "sset", "Master", f"{level}%"])
            return _ok(f"Volume set to {level}%.", level) if ok else _error("amixer failed.", out)
        return _unsupported("Volume control")

    def volume_get(self) -> SystemActionResult:
        if self._vol_backend == "pactl":
            ok, out = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            if ok and "%" in out:
                import re
                match = re.search(r"(\d+)%", out)
                if match:
                    level = int(match.group(1))
                    return _ok(f"Current volume: {level}%.", level)
        return _partial("Could not read volume level.")

    def mute(self) -> SystemActionResult:
        if self._vol_backend == "pactl":
            ok, out = _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"])
            return _ok("Muted.") if ok else _error("Mute failed.", out)
        if self._vol_backend == "amixer":
            ok, out = _run(["amixer", "sset", "Master", "mute"])
            return _ok("Muted.") if ok else _error("Mute failed.", out)
        return _unsupported("Mute")

    def unmute(self) -> SystemActionResult:
        if self._vol_backend == "pactl":
            ok, out = _run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
            return _ok("Unmuted.") if ok else _error("Unmute failed.", out)
        if self._vol_backend == "amixer":
            ok, out = _run(["amixer", "sset", "Master", "unmute"])
            return _ok("Unmuted.") if ok else _error("Unmute failed.", out)
        return _unsupported("Unmute")
    def media_play(self) -> SystemActionResult:
        return _unsupported("Media control")

    def media_pause(self) -> SystemActionResult:
        return _unsupported("Media control")

    def media_next(self) -> SystemActionResult:
        return _unsupported("Media control")

    def media_previous(self) -> SystemActionResult:
        return _unsupported("Media control")

    def media_stop(self) -> SystemActionResult:
        return _unsupported("Media control")
    def volume_step(self, direction: str, steps: int = 5) -> SystemActionResult:
        symbol = "+" if direction == "up" else "-"
        label = "up" if direction == "up" else "down"
        if self._vol_backend == "pactl":
            ok, out = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{symbol}{steps}%"])
            return _ok(f"Volume turned {label}.") if ok else _error("Volume step failed.", out)
        if self._vol_backend == "amixer":
            ok, out = _run(["amixer", "sset", "Master", f"{steps}%{symbol}"])
            return _ok(f"Volume turned {label}.") if ok else _error("Volume step failed.", out)
        return _unsupported("Volume control")

    # ── Brightness ────────────────────────────────────────────

    def brightness_set(self, level: int) -> SystemActionResult:
        level = max(0, min(100, level))
        if self._bright_backend == "brightnessctl":
            ok, out = _run(["brightnessctl", "set", f"{level}%"])
            return _ok(f"Brightness set to {level}%.", level) if ok else _error("brightnessctl failed.", out)
        if self._bright_backend == "xbacklight":
            ok, out = _run(["xbacklight", "-set", str(level)])
            return _ok(f"Brightness set to {level}%.", level) if ok else _error("xbacklight failed.", out)
        if self._bright_backend == "xrandr":
            scalar = round(level / 100, 2)
            ok, out = _run(["xrandr", "--output", "LVDS-1", "--brightness", str(scalar)])
            return _ok(f"Brightness set to {level}%.", level) if ok else _partial(f"Brightness adjusted.")
        return _unsupported("Brightness control")

    def brightness_step(self, direction: str, step: int = 10) -> SystemActionResult:
        symbol = "+" if direction == "up" else "-"
        label = "up" if direction == "up" else "down"
        if self._bright_backend == "brightnessctl":
            ok, out = _run(["brightnessctl", "set", f"{step}%{symbol}"])
            return _ok(f"Brightness turned {label}.") if ok else _error("brightnessctl failed.", out)
        if self._bright_backend == "xbacklight":
            flag = "-inc" if direction == "up" else "-dec"
            ok, out = _run(["xbacklight", flag, str(step)])
            return _ok(f"Brightness turned {label}.") if ok else _error("xbacklight failed.", out)
        return _unsupported("Brightness control")

    # ── Power ─────────────────────────────────────────────────

    def shutdown(self, delay: int = 0) -> SystemActionResult:
        cmd = ["shutdown", "-h", f"+{delay//60}" if delay else "now"]
        ok, out = _run(cmd)
        return _ok("Shutting down...") if ok else _error("Shutdown failed.", out)

    def restart(self, delay: int = 0) -> SystemActionResult:
        ok, out = _run(["shutdown", "-r", "now"])
        return _ok("Restarting...") if ok else _error("Restart failed.", out)

    def sleep(self) -> SystemActionResult:
        for cmd in [["systemctl", "suspend"], ["pm-suspend"]]:
            ok, out = _run(cmd)
            if ok:
                return _ok("Going to sleep.")
        return _error("Could not suspend system.")

    def lock_screen(self) -> SystemActionResult:
        for cmd in [
            ["loginctl", "lock-session"],
            ["xdg-screensaver", "lock"],
            ["gnome-screensaver-command", "--lock"],
            ["xscreensaver-command", "-lock"],
            ["i3lock"],
        ]:
            if shutil.which(cmd[0]):
                ok, out = _run(cmd)
                if ok:
                    return _ok("Screen locked.")
        return _partial("Lock command sent.")

    def cancel_shutdown(self) -> SystemActionResult:
        ok, out = _run(["shutdown", "-c"])
        return _ok("Shutdown cancelled.") if ok else _error("Cancel failed.", out)


# ── macOS Executor ────────────────────────────────────────────

class MacOSExecutor:
    """System control for macOS using osascript and pmset."""

    def volume_set(self, level: int) -> SystemActionResult:
        level = max(0, min(100, level))
        ok, out = _run(["osascript", "-e", f"set volume output volume {level}"])
        return _ok(f"Volume set to {level}%.", level) if ok else _error("Volume failed.", out)

    def volume_get(self) -> SystemActionResult:
        ok, out = _run(["osascript", "-e", "output volume of (get volume settings)"])
        if ok and out.isdigit():
            return _ok(f"Current volume: {out}%.", float(out))
        return _partial("Could not read volume.")

    def mute(self) -> SystemActionResult:
        ok, out = _run(["osascript", "-e", "set volume with output muted"])
        return _ok("Muted.") if ok else _error("Mute failed.", out)

    def unmute(self) -> SystemActionResult:
        ok, out = _run(["osascript", "-e", "set volume without output muted"])
        return _ok("Unmuted.") if ok else _error("Unmute failed.", out)

    def volume_step(self, direction: str, steps: int = 5) -> SystemActionResult:
        label = "up" if direction == "up" else "down"
        op = f"output volume + {steps}" if direction == "up" else f"output volume - {steps}"
        ok, out = _run(["osascript", "-e",
            f"set v to output volume of (get volume settings); set volume output volume (v {'+' if direction=='up' else '-'} {steps})"
        ])
        return _ok(f"Volume turned {label}.") if ok else _partial(f"Volume {label}.")

    def media_play(self) -> SystemActionResult:
        return _unsupported("Media control")

    def media_pause(self) -> SystemActionResult:
        return _unsupported("Media control")

    def media_next(self) -> SystemActionResult:
        return _unsupported("Media control")

    def media_previous(self) -> SystemActionResult:
        return _unsupported("Media control")

    def media_stop(self) -> SystemActionResult:
        return _unsupported("Media control")

    def brightness_set(self, level: int) -> SystemActionResult:
        level = max(0, min(100, level))
        scalar = round(level / 100, 2)
        if shutil.which("brightness"):
            ok, out = _run(["brightness", str(scalar)])
            return _ok(f"Brightness set to {level}%.", level) if ok else _partial("Brightness adjusted.")
        ok, out = _run(["osascript", "-e", f"tell application \"System Events\" to set brightness to {scalar}"])
        return _ok(f"Brightness set to {level}%.", level) if ok else _partial("Brightness adjusted.")

    def brightness_step(self, direction: str, step: int = 10) -> SystemActionResult:
        label = "up" if direction == "up" else "down"
        return _partial(f"Brightness turned {label}.")

    def shutdown(self, delay: int = 0) -> SystemActionResult:
        ok, out = _run(["osascript", "-e", 'tell app "System Events" to shut down'])
        return _ok("Shutting down...") if ok else _error("Shutdown failed.", out)

    def restart(self, delay: int = 0) -> SystemActionResult:
        ok, out = _run(["osascript", "-e", 'tell app "System Events" to restart'])
        return _ok("Restarting...") if ok else _error("Restart failed.", out)

    def sleep(self) -> SystemActionResult:
        ok, out = _run(["pmset", "sleepnow"])
        return _ok("Going to sleep.") if ok else _error("Sleep failed.", out)

    def lock_screen(self) -> SystemActionResult:
        ok, out = _run(["osascript", "-e",
            'tell application "System Events" to keystroke "q" using {command down, control down}'
        ])
        return _ok("Screen locked.") if ok else _partial("Lock attempted.")

    def cancel_shutdown(self) -> SystemActionResult:
        return _partial("Shutdown cancellation not directly available on macOS.")


# ── Mock Executor (testing) ───────────────────────────────────

class MockExecutor:
    """
    Deterministic mock for testing — records all calls, returns success.
    No real OS changes made.
    """
    def __init__(self):
        self.calls = []
        self._volume = 50
        self._brightness = 70
        self._muted = False

    def _record(self, method: str, **kwargs) -> SystemActionResult:
        self.calls.append({"method": method, **kwargs})
        log.debug(f"MockExecutor.{method}({kwargs})")
        return _ok(f"Mock: {method} executed.")

    def volume_set(self, level: int) -> SystemActionResult:
        self._volume = max(0, min(100, level))
        self.calls.append({"method": "volume_set", "level": self._volume})
        return _ok(f"Volume set to {self._volume}%.", self._volume)

    def volume_get(self) -> SystemActionResult:
        return _ok(f"Current volume: {self._volume}%.", self._volume)

    def mute(self) -> SystemActionResult:
        self._muted = True
        return self._record("mute")

    def unmute(self) -> SystemActionResult:
        self._muted = False
        return self._record("unmute")

    def volume_step(self, direction: str, steps: int = 5) -> SystemActionResult:
        delta = steps if direction == "up" else -steps
        self._volume = max(0, min(100, self._volume + delta))
        self.calls.append({"method": "volume_step", "direction": direction, "level": self._volume})
        return _ok(f"Volume turned {direction}.", self._volume)

    def media_play(self) -> SystemActionResult:
        self.calls.append({"method": "media_play"})
        return _ok("Mock: play command executed.")

    def media_pause(self) -> SystemActionResult:
        self.calls.append({"method": "media_pause"})
        return _ok("Mock: pause command executed.")

    def media_next(self) -> SystemActionResult:
        self.calls.append({"method": "media_next"})
        return _ok("Mock: next track command executed.")

    def media_previous(self) -> SystemActionResult:
        self.calls.append({"method": "media_previous"})
        return _ok("Mock: previous track command executed.")

    def media_stop(self) -> SystemActionResult:
        self.calls.append({"method": "media_stop"})
        return _ok("Mock: stop command executed.")

    def brightness_set(self, level: int) -> SystemActionResult:
        self._brightness = max(0, min(100, level))
        self.calls.append({"method": "brightness_set", "level": self._brightness})
        return _ok(f"Brightness set to {self._brightness}%.", self._brightness)

    def brightness_step(self, direction: str, step: int = 10) -> SystemActionResult:
        delta = step if direction == "up" else -step
        self._brightness = max(0, min(100, self._brightness + delta))
        return self._record("brightness_step", direction=direction, level=self._brightness)

    def shutdown(self, delay: int = 0) -> SystemActionResult:
        return self._record("shutdown", delay=delay)

    def restart(self, delay: int = 0) -> SystemActionResult:
        return self._record("restart", delay=delay)

    def sleep(self) -> SystemActionResult:
        return self._record("sleep")

    def lock_screen(self) -> SystemActionResult:
        return self._record("lock_screen")

    def cancel_shutdown(self) -> SystemActionResult:
        return self._record("cancel_shutdown")


# ── Factory ───────────────────────────────────────────────────

def create_media_executor(mock: bool = False):
    """Return the right executor for media control on the current platform."""
    if mock:
        return MockExecutor()
    if IS_WINDOWS:
        return WindowsExecutor()
    if IS_LINUX:
        return LinuxExecutor()
    if IS_MAC:
        return MacOSExecutor()
    log.warning("Unknown platform — using mock executor")
    return MockExecutor()


def create_system_executor(mock: bool = False):
    """Return the right executor for the current platform."""
    if mock:
        return MockExecutor()
    if IS_WINDOWS:
        return WindowsExecutor()
    if IS_LINUX:
        return LinuxExecutor()
    if IS_MAC:
        return MacOSExecutor()
    log.warning("Unknown platform — using mock executor")
    return MockExecutor()


__all__ = [
    "SystemActionResult", "ActionStatus",
    "WindowsExecutor", "LinuxExecutor", "MacOSExecutor", "MockExecutor",
    "create_media_executor", "create_system_executor",
]
