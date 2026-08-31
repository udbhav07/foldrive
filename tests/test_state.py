"""The snapshot: loading it, filling it in, and never writing half of it."""

import json
import os

import pytest

from foldrive import state
from foldrive.state import (
    EMPTY_STATE,
    STATE_DIR_NAME,
    STATE_FILE_NAME,
    load_state,
    save_state,
    state_path,
)


def write_state(folder, body):
    path = state_path(folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --- loading -----------------------------------------------------------------

def test_a_missing_state_file_loads_the_empty_skeleton(tmp_path):
    assert load_state(tmp_path) == EMPTY_STATE


def test_the_empty_skeleton_is_a_copy_not_the_shared_constant(tmp_path):
    """Callers mutate the state they are handed; the module constant must not
    pick those mutations up and leak them into the next folder."""
    loaded = load_state(tmp_path)
    loaded["files"]["a.txt"] = {"md5": "x"}
    assert EMPTY_STATE["files"] == {}
    assert load_state(tmp_path)["files"] == {}


def test_a_saved_state_round_trips(tmp_path):
    saved = {**EMPTY_STATE, "files": {"a.txt": {"size": 1, "mtime": 2.0, "md5": "x"}}}
    save_state(tmp_path, saved)
    assert load_state(tmp_path) == saved


def test_missing_keys_are_filled_in_from_the_skeleton(tmp_path):
    """An older state.json, or a hand-edited one, must not KeyError everything."""
    write_state(tmp_path, json.dumps({"files": {"a.txt": {"md5": "x"}}}))
    loaded = load_state(tmp_path)
    assert loaded["folders"] == {}
    assert loaded["last_pull_ok"] is None
    assert loaded["last_push_ok"] is None
    assert loaded["changes_page_token"] is None
    assert loaded["files"] == {"a.txt": {"md5": "x"}}


def test_stored_values_win_over_the_skeleton(tmp_path):
    write_state(tmp_path, json.dumps({"last_push_ok": "2026-08-12T00:00:00+00:00"}))
    assert load_state(tmp_path)["last_push_ok"] == "2026-08-12T00:00:00+00:00"


def test_corrupt_json_exits_with_the_recovery_instructions(tmp_path):
    """Refuses to guess. Deleting .foldrive/ is safe because the next sync is a
    first sync, which re-links both sides without deleting anything."""
    write_state(tmp_path, "{half a fi")
    with pytest.raises(SystemExit) as stop:
        load_state(tmp_path)
    message = str(stop.value)
    assert "is corrupt" in message
    assert STATE_DIR_NAME in message
    assert "foldrive sync" in message


# --- saving ------------------------------------------------------------------

def test_save_creates_the_state_directory(tmp_path):
    save_state(tmp_path, EMPTY_STATE)
    assert (tmp_path / STATE_DIR_NAME / STATE_FILE_NAME).exists()


def test_save_writes_a_temp_file_and_renames_it(tmp_path, monkeypatch):
    """Atomicity: the reader either sees the old snapshot or the new one."""
    seen = {}
    real_replace = os.replace

    def spy(source, destination):
        seen["source"] = str(source)
        seen["destination"] = str(destination)
        return real_replace(source, destination)

    monkeypatch.setattr(state.os, "replace", spy)
    save_state(tmp_path, EMPTY_STATE)

    assert seen["source"].endswith(STATE_FILE_NAME + ".tmp")
    assert seen["destination"].endswith(STATE_FILE_NAME)


def test_a_failed_rename_leaves_the_previous_snapshot_intact(tmp_path, monkeypatch):
    """The point of the temp file: a crash mid-save must not corrupt what was
    already there. The old state is still readable afterwards."""
    good = {**EMPTY_STATE, "files": {"kept.txt": {"md5": "original"}}}
    save_state(tmp_path, good)

    def replace_that_fails(source, destination):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr(state.os, "replace", replace_that_fails)
    with pytest.raises(OSError):
        save_state(tmp_path, {**EMPTY_STATE, "files": {"new.txt": {"md5": "later"}}})

    assert load_state(tmp_path)["files"] == {"kept.txt": {"md5": "original"}}


def test_saving_twice_overwrites_rather_than_appending(tmp_path):
    save_state(tmp_path, {**EMPTY_STATE, "files": {"a.txt": {"md5": "1"}}})
    save_state(tmp_path, {**EMPTY_STATE, "files": {"b.txt": {"md5": "2"}}})
    assert set(load_state(tmp_path)["files"]) == {"b.txt"}


def test_the_temp_file_does_not_survive_a_successful_save(tmp_path):
    save_state(tmp_path, EMPTY_STATE)
    assert not (tmp_path / STATE_DIR_NAME / (STATE_FILE_NAME + ".tmp")).exists()
