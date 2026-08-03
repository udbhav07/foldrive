"""Tests for the pure diff engine — one per row of the truth table in LLD.md 3.6."""

from datetime import datetime, timezone

from foldrive.engine import classify, conflict_copy_name, decide_conflict_winner

DRIVE_TIME = "2026-07-01T10:00:00.000Z"


def make_local(md5="aaa", mtime=1000.0):
    return {"size": 10, "mtime": mtime, "md5": md5}


def make_remote(md5="aaa", modified=DRIVE_TIME):
    return {"id": "drive1", "size": 10, "md5": md5, "modified": modified}


def make_snapshot(md5="aaa"):
    return {"size": 10, "mtime": 1000.0, "md5": md5,
            "drive_file_id": "drive1", "drive_modified": DRIVE_TIME}


def kinds(actions):
    """Shrink a result to just the action kinds, for readable assertions."""
    return [action.kind for action in actions]


def drive_time_near(epoch_seconds):
    """A Drive-format timestamp at the given epoch time."""
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).isoformat().replace("+00:00", "Z")


# --- no snapshot: this file pair has never been synced -----------------------

def test_new_local_file_is_uploaded():
    actions = classify({"a.pdf": make_local()}, {}, {})
    assert kinds(actions) == ["upload_new"]


def test_new_drive_file_is_downloaded():
    actions = classify({}, {"a.pdf": make_remote()}, {})
    assert kinds(actions) == ["download_new"]


def test_identical_files_are_linked():
    actions = classify({"a.pdf": make_local("same")}, {"a.pdf": make_remote("same")}, {})
    assert kinds(actions) == ["link"]


def test_different_files_with_no_history_conflict():
    actions = classify({"a.pdf": make_local("aaa")}, {"a.pdf": make_remote("bbb")}, {})
    assert kinds(actions) == ["conflict"]


# --- present on both sides, with a snapshot to compare against ---------------

def test_unchanged_file_produces_nothing():
    actions = classify(
        {"a.pdf": make_local("aaa")},
        {"a.pdf": make_remote("aaa")},
        {"a.pdf": make_snapshot("aaa")},
    )
    assert kinds(actions) == []


def test_locally_edited_file_is_uploaded():
    actions = classify(
        {"a.pdf": make_local("new")},
        {"a.pdf": make_remote("aaa")},
        {"a.pdf": make_snapshot("aaa")},
    )
    assert kinds(actions) == ["upload_changed"]


def test_drive_edited_file_is_downloaded():
    actions = classify(
        {"a.pdf": make_local("aaa")},
        {"a.pdf": make_remote("new")},
        {"a.pdf": make_snapshot("aaa")},
    )
    assert kinds(actions) == ["download_changed"]


def test_both_edited_is_a_conflict():
    actions = classify(
        {"a.pdf": make_local("new1")},
        {"a.pdf": make_remote("new2")},
        {"a.pdf": make_snapshot("aaa")},
    )
    assert kinds(actions) == ["conflict"]


# --- deletions ---------------------------------------------------------------

def test_locally_deleted_file_is_trashed():
    actions = classify({}, {"a.pdf": make_remote("aaa")}, {"a.pdf": make_snapshot("aaa")})
    assert kinds(actions) == ["trash_remote"]


def test_drive_deleted_file_is_recycled():
    actions = classify({"a.pdf": make_local("aaa")}, {}, {"a.pdf": make_snapshot("aaa")})
    assert kinds(actions) == ["recycle_local"]


def test_gone_from_both_sides_is_forgotten():
    actions = classify({}, {}, {"a.pdf": make_snapshot("aaa")})
    assert kinds(actions) == ["forget"]


# --- the safety rows: an edit must never be destroyed by a delete ------------

def test_edit_beats_delete_on_drive_side():
    """Deleted locally, but edited in Drive -> keep the Drive version."""
    actions = classify({}, {"a.pdf": make_remote("new")}, {"a.pdf": make_snapshot("aaa")})
    assert kinds(actions) == ["download_new"]


def test_edit_beats_delete_on_local_side():
    """Deleted in Drive, but edited locally -> keep the local version."""
    actions = classify({"a.pdf": make_local("new")}, {}, {"a.pdf": make_snapshot("aaa")})
    assert kinds(actions) == ["upload_new"]


# --- several files at once ---------------------------------------------------

def test_actions_are_sorted_by_path():
    actions = classify({"b.pdf": make_local(), "a.pdf": make_local()}, {}, {})
    assert [action.relpath for action in actions] == ["a.pdf", "b.pdf"]


# --- conflict winner ---------------------------------------------------------

def test_local_wins_when_newer():
    local = make_local(md5="new", mtime=1785000000.0)
    remote = make_remote(md5="old", modified="2026-01-01T10:00:00.000Z")
    assert decide_conflict_winner(local, remote) == "local"


def test_drive_wins_when_newer():
    local = make_local(md5="old", mtime=1700000000.0)
    remote = make_remote(md5="new", modified=drive_time_near(1785000000.0))
    assert decide_conflict_winner(local, remote) == "drive"


def test_close_timestamps_are_a_tie():
    local = make_local(md5="one", mtime=1785000000.0)
    remote = make_remote(md5="two", modified=drive_time_near(1785000002.0))
    assert decide_conflict_winner(local, remote) == ""


def test_missing_drive_time_is_a_tie():
    assert decide_conflict_winner(make_local(), make_remote(modified=None)) == ""


def test_classify_records_the_winner():
    actions = classify(
        {"a.pdf": make_local("new", mtime=1785000000.0)},
        {"a.pdf": make_remote("old", modified="2026-01-01T10:00:00.000Z")},
        {},
    )
    assert actions[0].winner == "local"


# --- conflict copy names -----------------------------------------------------

def test_conflict_copy_name_keeps_extension():
    assert conflict_copy_name("notes.docx", "local") == "notes (local copy).docx"


def test_conflict_copy_name_keeps_folder():
    assert conflict_copy_name("CN/notes.docx", "drive") == "CN/notes (drive copy).docx"


def test_conflict_copy_name_numbers_collisions():
    taken = {"notes (local copy).docx"}
    assert conflict_copy_name("notes.docx", "local", taken) == "notes (local copy 2).docx"


def test_conflict_copy_name_handles_no_extension():
    assert conflict_copy_name("README", "local") == "README (local copy)"
