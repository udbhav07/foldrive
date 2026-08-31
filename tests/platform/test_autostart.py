"""Registering the background tick, on both backends.

Everything here runs against a fake subprocess.run, so the cron tests pass on
Windows and the schtasks tests pass on Linux. That matters: these are the two
code paths a developer can least easily try by hand, and the cron one can
destroy data the tool does not own.
"""

import pytest

from foldrive import autostart
from foldrive.autostart import (
    CRON_MARKER,
    INTERVAL_MINUTES,
    TASK_NAME,
    _install_cron,
    _read_crontab,
    _status_cron,
    _uninstall_cron,
    _without_foldrive_lines,
)

FOREIGN_CRONTAB = (
    "0 3 * * * /usr/bin/backup-my-thesis\n"
    "*/15 * * * * /home/me/bin/check-mail\n"
)


class FakeRun:
    """Stands in for subprocess.run. Records every argv, answers by command."""

    def __init__(self, answers):
        self.answers = answers        # first argv word -> (returncode, stdout, stderr)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        command = argv[0] if isinstance(argv, list) else argv
        returncode, stdout, stderr = self.answers.get(command, (0, "", ""))
        return _Result(returncode, stdout, stderr)

    def argv_for(self, command):
        return [argv for argv, _kwargs in self.calls
                if (argv[0] if isinstance(argv, list) else argv) == command]

    def input_to(self, command):
        """Only the calls that wrote something - `crontab -l` passes no input."""
        return [kwargs["input"] for argv, kwargs in self.calls
                if (argv[0] if isinstance(argv, list) else argv) == command
                and kwargs.get("input") is not None]


class _Result:
    def __init__(self, returncode, stdout, stderr):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def crontab_holding(monkeypatch):
    """Install a fake crontab with the given contents; returns the FakeRun."""
    def install(text, list_returncode=0, list_stderr=""):
        fake = FakeRun({"crontab": (list_returncode, text, list_stderr)})
        monkeypatch.setattr(autostart.subprocess, "run", fake)
        monkeypatch.setattr(autostart.shutil, "which",
                            lambda name: f"/usr/local/bin/{name}")
        return fake

    return install


# --- _read_crontab -----------------------------------------------------------

def test_reading_an_existing_crontab_returns_it(crontab_holding):
    crontab_holding(FOREIGN_CRONTAB)
    assert _read_crontab() == FOREIGN_CRONTAB


def test_no_crontab_yet_is_an_empty_string_not_an_error(crontab_holding):
    """A normal first-run state: `crontab -l` exits 1 saying so."""
    crontab_holding("", list_returncode=1, list_stderr="no crontab for me")
    assert _read_crontab() == ""


def test_a_real_failure_raises_instead_of_returning_empty(crontab_holding):
    """The caller rewrites the whole crontab from what this returns, so
    mistaking an unreadable crontab for an empty one deletes every job the
    user has. It must refuse."""
    crontab_holding("", list_returncode=1, list_stderr="must be privileged to use -l")
    with pytest.raises(SystemExit, match="Could not read the crontab"):
        _read_crontab()


def test_the_refusal_carries_the_reason(crontab_holding):
    crontab_holding("", list_returncode=1, list_stderr="permission denied")
    with pytest.raises(SystemExit, match="permission denied"):
        _read_crontab()


# --- line filtering ----------------------------------------------------------

def test_foreign_lines_survive_the_filter():
    text = FOREIGN_CRONTAB + f"*/5 * * * * foldrive tick {CRON_MARKER}\n"
    assert _without_foldrive_lines(text) == FOREIGN_CRONTAB.splitlines()


def test_a_crontab_with_nothing_of_ours_is_unchanged():
    assert _without_foldrive_lines(FOREIGN_CRONTAB) == FOREIGN_CRONTAB.splitlines()


# --- install -----------------------------------------------------------------

def test_installing_preserves_every_foreign_line(crontab_holding):
    """cron has no append: the whole crontab is replaced on every write. This is
    the test that stands between a user and losing their own jobs."""
    fake = crontab_holding(FOREIGN_CRONTAB)
    _install_cron()

    written = fake.input_to("crontab")[-1]
    assert "/usr/bin/backup-my-thesis" in written
    assert "/home/me/bin/check-mail" in written


def test_installing_adds_one_marked_line(crontab_holding):
    fake = crontab_holding(FOREIGN_CRONTAB)
    _install_cron()

    written = fake.input_to("crontab")[-1]
    ours = [line for line in written.splitlines() if CRON_MARKER in line]
    assert len(ours) == 1
    assert ours[0].startswith(f"*/{INTERVAL_MINUTES} * * * *")
    assert "tick" in ours[0]


def test_installing_silences_the_job_so_cron_does_not_mail_it(crontab_holding):
    """cron mails the user anything a job prints, and foldrive already writes
    everything worth keeping to its log file."""
    fake = crontab_holding(FOREIGN_CRONTAB)
    _install_cron()
    ours = [line for line in fake.input_to("crontab")[-1].splitlines()
            if CRON_MARKER in line][0]
    assert ">/dev/null 2>&1" in ours


def test_installing_twice_does_not_leave_two_lines(crontab_holding):
    existing = FOREIGN_CRONTAB + f"*/5 * * * * /old/path/foldrive tick {CRON_MARKER}\n"
    fake = crontab_holding(existing)
    _install_cron()

    written = fake.input_to("crontab")[-1]
    assert len([line for line in written.splitlines() if CRON_MARKER in line]) == 1
    assert "/old/path/foldrive" not in written


def test_installing_uses_an_absolute_path(crontab_holding):
    """cron runs with a minimal PATH, so a bare `foldrive` may not resolve even
    though it works in your shell."""
    fake = crontab_holding("")
    _install_cron()
    ours = [line for line in fake.input_to("crontab")[-1].splitlines()
            if CRON_MARKER in line][0]
    assert "/usr/local/bin/foldrive" in ours


def test_installing_without_cron_installed_exits(monkeypatch):
    monkeypatch.setattr(autostart.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="No `crontab` command found"):
        _install_cron()


def test_a_failing_write_is_reported(monkeypatch):
    fake = FakeRun({"crontab": (0, "", "")})

    def run_that_fails_on_write(argv, **kwargs):
        fake.calls.append((argv, kwargs))
        if kwargs.get("input") is not None:
            return _Result(1, "", "crontab: installing new crontab failed")
        return _Result(0, "", "")

    monkeypatch.setattr(autostart.subprocess, "run", run_that_fails_on_write)
    monkeypatch.setattr(autostart.shutil, "which", lambda name: "/usr/local/bin/foldrive")

    with pytest.raises(SystemExit, match="Could not update crontab"):
        _install_cron()


# --- uninstall ---------------------------------------------------------------

def test_uninstalling_removes_only_our_lines(crontab_holding):
    existing = FOREIGN_CRONTAB + f"*/5 * * * * /usr/local/bin/foldrive tick {CRON_MARKER}\n"
    fake = crontab_holding(existing)
    _uninstall_cron()

    written = fake.input_to("crontab")[-1]
    assert CRON_MARKER not in written
    assert "/usr/bin/backup-my-thesis" in written
    assert "/home/me/bin/check-mail" in written


def test_uninstalling_when_it_was_never_installed_exits(crontab_holding):
    fake = crontab_holding(FOREIGN_CRONTAB)
    with pytest.raises(SystemExit, match="was not enabled"):
        _uninstall_cron()
    assert fake.input_to("crontab") == []      # nothing was rewritten


# --- status ------------------------------------------------------------------

def test_status_returns_our_line_when_registered(crontab_holding):
    line = f"*/5 * * * * /usr/local/bin/foldrive tick >/dev/null 2>&1 {CRON_MARKER}"
    crontab_holding(FOREIGN_CRONTAB + line + "\n")
    assert _status_cron() == line


def test_status_says_not_registered_otherwise(crontab_holding):
    crontab_holding(FOREIGN_CRONTAB)
    assert _status_cron() == "not registered"


# --- the Windows backend -----------------------------------------------------

@pytest.fixture
def schtasks(monkeypatch):
    fake = FakeRun({"schtasks": (0, f"TaskName: {TASK_NAME}", ""),
                    "powershell": (0, "", "")})
    monkeypatch.setattr(autostart.subprocess, "run", fake)
    return fake


def test_windows_install_registers_the_task_every_five_minutes(schtasks, monkeypatch):
    monkeypatch.setattr(autostart, "_foldrive_command", lambda: '"py.exe" tick')
    autostart._install_windows()

    argv = schtasks.argv_for("schtasks")[0]
    assert argv[:3] == ["schtasks", "/create", "/tn"]
    assert argv[3] == TASK_NAME
    assert argv[argv.index("/mo") + 1] == str(INTERVAL_MINUTES)
    assert argv[argv.index("/sc") + 1] == "minute"
    assert "/f" in argv


def test_windows_install_relaxes_the_battery_settings(schtasks, monkeypatch):
    """schtasks refuses to start on battery and kills a running task the moment
    you unplug - which stopped ticks for three hours before it was found."""
    monkeypatch.setattr(autostart, "_foldrive_command", lambda: '"py.exe" tick')
    assert autostart._install_windows() is True

    script = schtasks.argv_for("powershell")[0][-1]
    assert "DisallowStartIfOnBatteries = $false" in script
    assert "StopIfGoingOnBatteries = $false" in script
    assert TASK_NAME in script


def test_a_failed_battery_patch_does_not_fail_the_install(monkeypatch):
    """Best-effort: the task still syncs on mains power, which is worth keeping
    rather than failing the whole install over."""
    fake = FakeRun({"schtasks": (0, "", ""), "powershell": (1, "", "denied")})
    monkeypatch.setattr(autostart.subprocess, "run", fake)
    monkeypatch.setattr(autostart, "_foldrive_command", lambda: '"py.exe" tick')

    assert autostart._install_windows() is False


def test_windows_uninstall_deletes_the_task(schtasks):
    autostart._uninstall_windows()
    argv = schtasks.argv_for("schtasks")[0]
    assert argv == ["schtasks", "/delete", "/tn", TASK_NAME, "/f"]


def test_windows_status_reports_the_task(schtasks):
    assert TASK_NAME in autostart._status_windows()


def test_windows_status_says_not_registered_when_missing(monkeypatch):
    fake = FakeRun({"schtasks": (1, "", "ERROR: cannot find the file specified")})
    monkeypatch.setattr(autostart.subprocess, "run", fake)
    assert autostart._status_windows() == "not registered"


# --- dispatch ----------------------------------------------------------------

@pytest.mark.parametrize("platform,expected", [
    ("win32", "_install_windows"),
    ("linux", "_install_cron"),
    ("darwin", "_install_cron"),
])
def test_install_picks_the_backend_for_the_platform(platform, expected, monkeypatch):
    reached = []
    monkeypatch.setattr(autostart.sys, "platform", platform)
    for name in ("_install_windows", "_install_cron"):
        monkeypatch.setattr(autostart, name,
                            lambda got=name: reached.append(got))
    autostart.install()
    assert reached == [expected]


@pytest.mark.parametrize("platform,expected", [
    ("win32", "_uninstall_windows"),
    ("linux", "_uninstall_cron"),
])
def test_uninstall_picks_the_backend_for_the_platform(platform, expected, monkeypatch):
    reached = []
    monkeypatch.setattr(autostart.sys, "platform", platform)
    for name in ("_uninstall_windows", "_uninstall_cron"):
        monkeypatch.setattr(autostart, name, lambda got=name: reached.append(got))
    autostart.uninstall()
    assert reached == [expected]


@pytest.mark.parametrize("platform,expected", [
    ("win32", "_status_windows"),
    ("linux", "_status_cron"),
])
def test_status_picks_the_backend_for_the_platform(platform, expected, monkeypatch):
    reached = []
    monkeypatch.setattr(autostart.sys, "platform", platform)
    for name in ("_status_windows", "_status_cron"):
        monkeypatch.setattr(autostart, name, lambda got=name: reached.append(got))
    autostart.status()
    assert reached == [expected]


# --- the command foldrive registers ------------------------------------------

def test_the_cron_command_falls_back_to_the_interpreter(monkeypatch):
    monkeypatch.setattr(autostart.shutil, "which", lambda name: None)
    assert autostart._cron_command().endswith("-m foldrive.cli tick")


def test_the_windows_command_prefers_pythonw(monkeypatch, tmp_path):
    """A console script would flash a command prompt at every scheduled tick."""
    interpreter = tmp_path / "python.exe"
    interpreter.write_text("", encoding="utf-8")
    (tmp_path / "pythonw.exe").write_text("", encoding="utf-8")
    monkeypatch.setattr(autostart.sys, "executable", str(interpreter))
    monkeypatch.setattr(autostart.sys, "frozen", False, raising=False)

    command = autostart._foldrive_command()
    assert "pythonw.exe" in command
    assert command.endswith("-m foldrive.cli tick")


def test_the_windows_command_uses_the_frozen_exe_when_there_is_one(monkeypatch):
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\Program Files\foldrive.exe")
    assert autostart._foldrive_command() == r'"C:\Program Files\foldrive.exe" tick'
