"""Registers foldrive tick with Windows Task Scheduler."""

import shutil
import subprocess
import sys
from pathlib import Path

TASK_NAME = "foldrive-tick"
INTERVAL_MINUTES = 5

# schtasks' defaults are wrong for a laptop sync tool: it refuses to start on
# battery and kills a running task the moment you unplug. Those flags can't be set
# from the schtasks command line, and registering from XML needs elevation, so the
# task is created the plain way and then patched through the PowerShell API.
POWER_SETTINGS_SCRIPT = f"""
$task = Get-ScheduledTask -TaskName '{TASK_NAME}'
$task.Settings.DisallowStartIfOnBatteries = $false
$task.Settings.StopIfGoingOnBatteries = $false
$task.Settings.MultipleInstances = 'IgnoreNew'
$task.Settings.StartWhenAvailable = $true
$task | Set-ScheduledTask | Out-Null
"""

WINDOWS_ONLY_MESSAGE = (
    "Background sync is Windows-only for now.\n"
    "Everything else works: run `foldrive sync` when you want to sync, or add a\n"
    "cron entry to do it automatically:\n"
    "    */5 * * * * foldrive tick"
)

def _require_windows():
    """sys.platform is "win32" on every Windows, 32- or 64-bit - there is no "win64"."""
    if sys.platform != "win32":
        raise SystemExit(WINDOWS_ONLY_MESSAGE)


def _foldrive_command():
    """The command Task Scheduler should run, however foldrive was installed.

    Always an absolute path: the task runs with a different environment and
    working directory, so a bare `foldrive` may not resolve.

    Prefers pythonw.exe: it belongs to the GUI subsystem, so Windows never
    allocates a console for it. Running foldrive.exe (a console script) would
    flash a command prompt on screen at every scheduled tick.
    """
    if getattr(sys, "frozen", False):
        # Standalone foldrive.exe (PyInstaller build; needs --noconsole to be quiet).
        return f'"{sys.executable}" tick'

    windowless_python = Path(sys.executable).with_name("pythonw.exe")
    if windowless_python.exists():
        return f'"{windowless_python}" -m foldrive.cli tick'

    installed_path = shutil.which("foldrive")
    if installed_path:
        return f'"{installed_path}" tick'

    # Installed but not on PATH - call this same interpreter's module directly.
    return f'"{sys.executable}" -m foldrive.cli tick'


def _allow_running_on_battery():
    """Returns True if the power settings were relaxed.

    Best-effort: if it fails, the task still syncs whenever the machine is plugged
    in, which is worth keeping rather than failing the whole install over.
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", POWER_SETTINGS_SCRIPT],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def install():
    _require_windows()
    subprocess.run([
        "schtasks", "/create", "/tn", TASK_NAME,
        "/tr", _foldrive_command(),
        "/sc", "minute", "/mo", str(INTERVAL_MINUTES),
        "/f",
    ], check=True)
    return _allow_running_on_battery()


def uninstall():
    _require_windows()
    subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], check=True)


def status():
    # Reports rather than raises: `--status` is a question, and "not supported here"
    # is a perfectly good answer to it.
    if sys.platform != "win32":
        return "not supported on this platform (background sync is Windows-only)"
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "not registered"
