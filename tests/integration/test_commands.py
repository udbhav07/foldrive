"""The commands, with only auth and drive replaced.

Each test chdirs into a real folder on disk and calls the command's own run(),
so the argument handling, the config lookup, the timestamp bookkeeping and the
printed summary are all the production ones.
"""

import json
from argparse import Namespace

import pytest

from foldrive import auth, config, logs, scheduler, state
from foldrive.commands import pull, push, status, tick


@pytest.fixture
def logged_in(monkeypatch):
    """Past the auth wall. drive.* is already the fake, so the value is unused."""
    monkeypatch.setattr(auth, "get_service", lambda: None)
    monkeypatch.setattr(auth, "get_credentials", lambda: "a-credential")


@pytest.fixture
def in_folder(monkeypatch, synced_folder):
    monkeypatch.chdir(synced_folder)
    return synced_folder


class RecordingLogger:
    """Stands in for the rotating file logger. tick's whole contract is that it
    says why it did nothing, so the tests read what it said."""

    def __init__(self):
        self.lines = []

    def _record(self, level, message, *args, **kwargs):
        self.lines.append((level, str(message)))

    def info(self, message, *a, **k):
        self._record("info", message)

    def warning(self, message, *a, **k):
        self._record("warning", message)

    def error(self, message, *a, **k):
        self._record("error", message)

    def exception(self, message, *a, **k):
        self._record("exception", message)


@pytest.fixture
def logger(monkeypatch):
    recorder = RecordingLogger()
    monkeypatch.setattr(logs, "get_logger", lambda: recorder)
    return recorder


def messages(recorder, level=None):
    return [text for got_level, text in recorder.lines
            if level is None or got_level == level]


# --- status ------------------------------------------------------------------

def test_status_counts_both_sides(capsys, in_folder, fake_drive, logged_in):
    (in_folder / "local-only.txt").write_text("a", encoding="utf-8")
    fake_drive.put("drive-only.txt", b"b")

    status.run(Namespace(all=False))
    printed = capsys.readouterr().out

    assert "Local  : 1 files    Drive: 1 files" in printed
    assert "upload" in printed
    assert "download" in printed
    assert "2 change(s) pending" in printed


def test_status_says_when_everything_is_in_sync(capsys, in_folder, fake_drive, logged_in):
    status.run(Namespace(all=False))
    assert "Everything is in sync." in capsys.readouterr().out


def test_status_announces_a_first_sync(capsys, in_folder, fake_drive, logged_in):
    (in_folder / "a.txt").write_text("a", encoding="utf-8")
    status.run(Namespace(all=False))
    assert "never been synced" in capsys.readouterr().out


def test_status_never_writes_the_snapshot(in_folder, fake_drive, logged_in):
    """status is read-only. Writing a snapshot here would silently link files
    that were never actually transferred."""
    (in_folder / "a.txt").write_text("a", encoding="utf-8")
    fake_drive.put("b.txt", b"b")

    status.run(Namespace(all=False))

    assert not state.state_path(in_folder).exists()


def test_status_caps_the_listing_without_all(capsys, in_folder, fake_drive, logged_in):
    for n in range(45):
        (in_folder / f"f-{n:03}.txt").write_text(str(n), encoding="utf-8")

    status.run(Namespace(all=False))
    printed = capsys.readouterr().out

    assert "and 5 more" in printed
    assert "f-044.txt" not in printed


def test_status_all_lists_everything(capsys, in_folder, fake_drive, logged_in):
    for n in range(45):
        (in_folder / f"f-{n:03}.txt").write_text(str(n), encoding="utf-8")

    status.run(Namespace(all=True))
    printed = capsys.readouterr().out

    assert "more (use --all" not in printed
    assert "f-044.txt" in printed


def test_status_reports_a_never_delete_note(capsys, in_folder, fake_drive, logged_in):
    (in_folder / "a.txt").write_text("a", encoding="utf-8")
    fake_drive.put("a.txt", b"a")
    push.run(Namespace(yes=True, allow_mass_delete=False))
    fake_drive.files.pop("a.txt")

    folder_config = json.loads((in_folder / config.CONFIG_NAME).read_text(encoding="utf-8"))
    folder_config["delete_policy"] = {"local": "never_delete", "drive": "trash"}
    (in_folder / config.CONFIG_NAME).write_text(json.dumps(folder_config), encoding="utf-8")

    capsys.readouterr()
    status.run(Namespace(all=False))
    printed = capsys.readouterr().out

    assert "kept locally" in printed
    assert (in_folder / "a.txt").exists()


def test_status_outside_a_foldrive_folder_exits(tmp_path, monkeypatch, logged_in):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit, match="Not a foldrive folder"):
        status.run(Namespace(all=False))


# --- push / pull timestamps --------------------------------------------------

def test_push_records_the_time_it_succeeded(in_folder, fake_drive, logged_in):
    (in_folder / "a.txt").write_text("a", encoding="utf-8")
    push.run(Namespace(yes=True, allow_mass_delete=False))

    saved = state.load_state(in_folder)
    assert saved["last_push_ok"] is not None
    assert saved["last_pull_ok"] is None
    assert fake_drive.contents() == {"a.txt": b"a"}


def test_pull_records_the_time_it_succeeded(in_folder, fake_drive, logged_in):
    fake_drive.put("a.txt", b"a")
    pull.run(Namespace(yes=True, allow_mass_delete=False))

    saved = state.load_state(in_folder)
    assert saved["last_pull_ok"] is not None
    assert saved["last_push_ok"] is None
    assert (in_folder / "a.txt").read_bytes() == b"a"


def test_nothing_to_push_still_counts_as_a_success(capsys, in_folder, fake_drive,
                                                   logged_in):
    """Otherwise the folder stays overdue forever and every tick rescans it
    for nothing."""
    push.run(Namespace(yes=True, allow_mass_delete=False))

    assert "Nothing to push." in capsys.readouterr().out
    assert state.load_state(in_folder)["last_push_ok"] is not None


def test_nothing_to_pull_still_counts_as_a_success(capsys, in_folder, fake_drive,
                                                   logged_in):
    pull.run(Namespace(yes=True, allow_mass_delete=False))

    assert "Nothing to pull." in capsys.readouterr().out
    assert state.load_state(in_folder)["last_pull_ok"] is not None


def test_push_prints_its_summary(capsys, in_folder, fake_drive, logged_in):
    (in_folder / "a.txt").write_text("a", encoding="utf-8")
    push.run(Namespace(yes=True, allow_mass_delete=False))
    assert "uploaded 1, updated 0, trashed 0" in capsys.readouterr().out


def test_pull_prints_its_summary(capsys, in_folder, fake_drive, logged_in):
    fake_drive.put("a.txt", b"a")
    pull.run(Namespace(yes=True, allow_mass_delete=False))
    assert "downloaded 1, updated 0, recycled 0" in capsys.readouterr().out


def test_a_first_sync_deletes_nothing(in_folder, fake_drive, logged_in):
    """Both sides have files the other has never seen. A first sync merges them."""
    (in_folder / "mine.txt").write_text("mine", encoding="utf-8")
    fake_drive.put("theirs.txt", b"theirs")

    pull.run(Namespace(yes=True, allow_mass_delete=False))
    push.run(Namespace(yes=True, allow_mass_delete=False))

    assert (in_folder / "mine.txt").exists()
    assert (in_folder / "theirs.txt").exists()
    assert set(fake_drive.contents()) == {"mine.txt", "theirs.txt"}


def test_the_mass_delete_guard_stops_a_push(in_folder, fake_drive, logged_in):
    for n in range(20):
        (in_folder / f"f-{n:02}.txt").write_text(str(n), encoding="utf-8")
    push.run(Namespace(yes=True, allow_mass_delete=False))

    for n in range(20):
        (in_folder / f"f-{n:02}.txt").unlink()

    with pytest.raises(SystemExit, match="Refusing to continue"):
        push.run(Namespace(yes=True, allow_mass_delete=False))
    assert len(fake_drive.contents()) == 20


def test_allow_mass_delete_overrides_the_guard(in_folder, fake_drive, logged_in):
    for n in range(20):
        (in_folder / f"f-{n:02}.txt").write_text(str(n), encoding="utf-8")
    push.run(Namespace(yes=True, allow_mass_delete=False))

    for n in range(20):
        (in_folder / f"f-{n:02}.txt").unlink()

    push.run(Namespace(yes=True, allow_mass_delete=True))
    assert fake_drive.contents() == {}


# --- tick --------------------------------------------------------------------

def test_tick_says_so_when_offline(logger, monkeypatch):
    monkeypatch.setattr(scheduler, "is_online", lambda: False)
    monkeypatch.setattr(config, "registered_folders",
                        lambda: pytest.fail("must not look at folders when offline"))

    tick.run(Namespace())

    assert messages(logger, "info") == ["offline-nothing attempted"]


def test_tick_says_so_when_not_logged_in(logger, monkeypatch):
    """Permanent until a human acts, so it is said once, not once per folder."""
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(auth, "get_credentials", lambda: None)
    monkeypatch.setattr(config, "registered_folders",
                        lambda: pytest.fail("must not look at folders when logged out"))

    tick.run(Namespace())

    assert any("not logged in" in text for text in messages(logger, "error"))


def test_tick_says_so_when_no_folders_are_registered(logger, monkeypatch, logged_in):
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [])

    tick.run(Namespace())

    assert messages(logger, "info") == ["no registered folders"]


def test_tick_skips_a_folder_that_was_never_synced(logger, monkeypatch, logged_in,
                                                   synced_folder):
    """A first sync merges two unknown trees; a human should watch that happen."""
    ran = []
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [synced_folder])
    monkeypatch.setattr(pull, "run", lambda args: ran.append("pull"))
    monkeypatch.setattr(push, "run", lambda args: ran.append("push"))

    tick.run(Namespace())

    assert ran == []
    assert any("never synced" in text for text in messages(logger, "warning"))


def test_tick_runs_a_folder_that_is_due(logger, monkeypatch, logged_in, synced_folder):
    ran = []
    state.save_state(synced_folder, {**state.EMPTY_STATE,
                                     "files": {"a.txt": {"md5": "x"}}})
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [synced_folder])
    monkeypatch.setattr(pull, "run", lambda args: ran.append("pull"))
    monkeypatch.setattr(push, "run", lambda args: ran.append("push"))

    tick.run(Namespace())

    assert ran == ["pull", "push"]
    assert any("pull ok" in text for text in messages(logger, "info"))


def test_tick_leaves_a_folder_that_is_not_due(logger, monkeypatch, logged_in,
                                              synced_folder):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    state.save_state(synced_folder, {**state.EMPTY_STATE,
                                     "files": {"a.txt": {"md5": "x"}},
                                     "last_pull_ok": now, "last_push_ok": now})
    ran = []
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [synced_folder])
    monkeypatch.setattr(pull, "run", lambda args: ran.append("pull"))
    monkeypatch.setattr(push, "run", lambda args: ran.append("push"))

    tick.run(Namespace())

    assert ran == []


def test_tick_never_prompts(monkeypatch, logger, logged_in, synced_folder):
    """A scheduled run has nobody to answer, so yes=True is not optional."""
    seen = []
    state.save_state(synced_folder, {**state.EMPTY_STATE,
                                     "files": {"a.txt": {"md5": "x"}}})
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [synced_folder])
    monkeypatch.setattr(pull, "run", lambda args: seen.append(args))
    monkeypatch.setattr(push, "run", lambda args: seen.append(args))

    tick.run(Namespace())

    assert all(args.yes is True for args in seen)


def test_one_broken_folder_does_not_kill_the_rest(logger, monkeypatch, logged_in,
                                                  tmp_path):
    """SystemExit is a BaseException, so a bare `except Exception` here would let
    one corrupt config file stop every folder after it."""
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / config.CONFIG_NAME).write_text("{ not json", encoding="utf-8")

    healthy = tmp_path / "healthy"
    healthy.mkdir()
    (healthy / config.CONFIG_NAME).write_text(
        json.dumps({"drive_folder_id": "root"}), encoding="utf-8")
    state.save_state(healthy, {**state.EMPTY_STATE, "files": {"a.txt": {"md5": "x"}}})

    ran = []
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [broken, healthy])
    monkeypatch.setattr(pull, "run", lambda args: ran.append("pull"))
    monkeypatch.setattr(push, "run", lambda args: ran.append("push"))

    tick.run(Namespace())

    assert ran == ["pull", "push"]
    assert any("broken" in text for text in messages(logger, "exception"))


def test_tick_returns_to_the_directory_it_started_in(monkeypatch, logger, logged_in,
                                                     synced_folder, tmp_path):
    import os

    start = tmp_path / "elsewhere"
    start.mkdir()
    monkeypatch.chdir(start)
    state.save_state(synced_folder, {**state.EMPTY_STATE,
                                     "files": {"a.txt": {"md5": "x"}}})
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [synced_folder])
    monkeypatch.setattr(pull, "run", lambda args: None)
    monkeypatch.setattr(push, "run", lambda args: None)

    tick.run(Namespace())

    assert os.getcwd() == str(start.resolve())


def test_a_folder_that_exits_is_logged_and_the_tick_survives(logger, monkeypatch,
                                                             logged_in, synced_folder):
    """A command raising SystemExit mid-run is a stopped folder, not a stopped tick."""
    state.save_state(synced_folder, {**state.EMPTY_STATE,
                                     "files": {"a.txt": {"md5": "x"}}})

    def pull_that_exits(args):
        raise SystemExit("Refusing to continue: this would delete everything")

    ran = []
    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [synced_folder])
    monkeypatch.setattr(pull, "run", pull_that_exits)
    monkeypatch.setattr(push, "run", lambda args: ran.append("push"))

    tick.run(Namespace())

    assert ran == ["push"]
    assert any("stopped" in text for text in messages(logger, "error"))


def test_a_lost_network_mid_tick_is_a_warning_not_a_crash(logger, monkeypatch,
                                                          logged_in, synced_folder):
    state.save_state(synced_folder, {**state.EMPTY_STATE,
                                     "files": {"a.txt": {"md5": "x"}}})

    def pull_that_loses_the_network(args):
        raise OSError("connection reset by peer")

    monkeypatch.setattr(scheduler, "is_online", lambda: True)
    monkeypatch.setattr(config, "registered_folders", lambda: [synced_folder])
    monkeypatch.setattr(pull, "run", pull_that_loses_the_network)
    monkeypatch.setattr(push, "run", lambda args: None)

    tick.run(Namespace())

    assert any("lost the network" in text for text in messages(logger, "warning"))
