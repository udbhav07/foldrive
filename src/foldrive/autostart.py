"""Registers `foldrive tick` to run in the background.

Windows uses Task Scheduler; everything else uses cron. The public install/
uninstall/status functions dispatch on platform, so each backend below can assume
it is only ever called on its own OS.
"""

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
    if sys.platform == "win32":
        return _install_windows()
    return _install_cron()

def uninstall():
    if sys.platform == "win32":
        return _uninstall_windows()
    return _uninstall_cron()


def status():
    if sys.platform == "win32":
        return _status_windows()
    return _status_cron()



def _install_windows():
    subprocess.run([
        "schtasks", "/create", "/tn", TASK_NAME,
        "/tr", _foldrive_command(),
        "/sc", "minute", "/mo", str(INTERVAL_MINUTES),
        "/f",
    ], check=True)
    return _allow_running_on_battery()


def _uninstall_windows():
    subprocess.run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"], check=True)


def _status_windows():
    result = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else "not registered"

CRON_MARKER = "# foldrive-tick"


def _read_crontab():
    """Empty string when there is no crontab yet.

    `crontab -l` exits 1 with "no crontab for <user>" in that case - a normal
    first-run state, not a failure, so this must not use check=True.

    Any OTHER failure must raise rather than return "": the caller rewrites the
    whole crontab from what this returns, so mistaking an unreadable crontab for
    an empty one would delete every job the user has.
    """
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout
    if "no crontab" in result.stderr.lower():
        return ""
    raise SystemExit(f"Could not read the crontab: {result.stderr.strip()}")


def _write_crontab(lines):
    """cron has no 'append' - the whole crontab is replaced every time. That is
    exactly why every foldrive line carries CRON_MARKER: so we can strip ours and
    put everyone else's back untouched."""
    text = "\n".join(lines).strip() + "\n"
    result = subprocess.run(["crontab", "-"], input=text, text=True, capture_output=True)
    if result.returncode != 0:
        raise SystemExit(f"Could not update crontab: {result.stderr.strip()}")


def _without_foldrive_lines(text):
    return [line for line in text.splitlines() if CRON_MARKER not in line]


def _cron_command():
    """Absolute path: cron runs with a minimal PATH (usually /usr/bin:/bin), so a
    bare `foldrive` may not resolve even though it works in your shell."""
    installed_path = shutil.which("foldrive")
    if installed_path:
        return f"{installed_path} tick"
    return f"{sys.executable} -m foldrive.cli tick"


def _install_cron():
    if shutil.which("crontab") is None:
        raise SystemExit(
            "No `crontab` command found. Install cron, or run `foldrive sync` manually."
        )
    lines = _without_foldrive_lines(_read_crontab())
    # >/dev/null: cron mails the user any output a job produces, and foldrive
    # already writes everything worth keeping to its log file.
    lines.append(
        f"*/{INTERVAL_MINUTES} * * * * {_cron_command()} >/dev/null 2>&1 {CRON_MARKER}"
    )
    _write_crontab(lines)
    return True          # cron has no battery restriction to relax


def _uninstall_cron():
    existing = _read_crontab()
    remaining = _without_foldrive_lines(existing)
    if len(remaining) == len(existing.splitlines()):
        raise SystemExit("Background sync was not enabled.")
    _write_crontab(remaining)


def _status_cron():
    for line in _read_crontab().splitlines():
        if CRON_MARKER in line:
            return line.strip()
    return "not registered"