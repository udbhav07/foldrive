"""The per-folder journal: what foldrive did, in the order it did it.

JSONL, so appending is one write with no parsing and a truncated last line from
a crash costs one record instead of the file.
"""

import json

from foldrive import history
from foldrive.history import (
    MAX_HISTORY_BYTES,
    history_path,
    read,
    record,
    trim_if_large,
)


def lines_in(folder):
    return history_path(folder).read_text(encoding="utf-8").splitlines()


# --- record / read round trip ------------------------------------------------

def test_reading_an_absent_history_returns_nothing(tmp_path):
    assert read(tmp_path) == []


def test_a_recorded_action_comes_back(tmp_path):
    record(tmp_path, "upload_new", "notes/cn.pdf", "drive-1")
    entry = read(tmp_path)[0]
    assert entry["kind"] == "upload_new"
    assert entry["path"] == "notes/cn.pdf"
    assert entry["drive_file_id"] == "drive-1"
    assert entry["at"].startswith("20")


def test_the_drive_id_is_omitted_when_there_is_none(tmp_path):
    record(tmp_path, "recycle_local", "gone.txt")
    assert "drive_file_id" not in read(tmp_path)[0]


def test_each_record_is_one_line(tmp_path):
    for n in range(3):
        record(tmp_path, "upload_new", f"f-{n}.txt")
    assert len(lines_in(tmp_path)) == 3


def test_history_is_newest_first(tmp_path):
    for n in range(3):
        record(tmp_path, "upload_new", f"f-{n}.txt")
    assert [entry["path"] for entry in read(tmp_path)] == ["f-2.txt", "f-1.txt", "f-0.txt"]


def test_the_limit_takes_the_newest_entries(tmp_path):
    for n in range(10):
        record(tmp_path, "upload_new", f"f-{n}.txt")
    newest = read(tmp_path, limit=3)
    assert [entry["path"] for entry in newest] == ["f-9.txt", "f-8.txt", "f-7.txt"]


def test_record_creates_the_state_directory(tmp_path):
    record(tmp_path, "upload_new", "a.txt")
    assert history_path(tmp_path).exists()


# --- damaged files -----------------------------------------------------------

def test_a_malformed_line_is_skipped_not_fatal(tmp_path):
    """A half-written line from a killed process must not make the rest
    unreadable - that would lose the whole journal to one bad byte."""
    record(tmp_path, "upload_new", "good-1.txt")
    with open(history_path(tmp_path), "a", encoding="utf-8") as handle:
        handle.write('{"kind": "upload_new", "path": "trunc\n')
    record(tmp_path, "upload_new", "good-2.txt")

    paths = [entry["path"] for entry in read(tmp_path)]
    assert paths == ["good-2.txt", "good-1.txt"]


def test_blank_lines_are_ignored(tmp_path):
    record(tmp_path, "upload_new", "a.txt")
    with open(history_path(tmp_path), "a", encoding="utf-8") as handle:
        handle.write("\n   \n")
    assert len(read(tmp_path)) == 1


def test_a_history_of_nothing_but_garbage_reads_as_empty(tmp_path):
    history_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    history_path(tmp_path).write_text("not json at all\n{{{\n", encoding="utf-8")
    assert read(tmp_path) == []


# --- record never raises -----------------------------------------------------

def test_record_swallows_an_unwritable_path(tmp_path, monkeypatch):
    """Losing a history line must never fail a sync that actually succeeded."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    monkeypatch.setattr(history, "history_path",
                        lambda folder: blocker / "sub" / "history.jsonl")
    record(tmp_path, "upload_new", "a.txt")     # must not raise


def test_record_swallows_a_failing_open(tmp_path, monkeypatch):
    def open_that_fails(*args, **kwargs):
        raise OSError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", open_that_fails)
    record(tmp_path, "upload_new", "a.txt")     # must not raise


# --- trimming ----------------------------------------------------------------

def test_a_small_history_is_left_alone(tmp_path):
    record(tmp_path, "upload_new", "a.txt")
    before = history_path(tmp_path).read_text(encoding="utf-8")
    trim_if_large(tmp_path)
    assert history_path(tmp_path).read_text(encoding="utf-8") == before


def test_trimming_an_absent_history_does_nothing(tmp_path):
    trim_if_large(tmp_path)     # must not raise
    assert not history_path(tmp_path).exists()


def test_a_large_history_loses_its_older_half(tmp_path):
    path = history_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [json.dumps({"at": "2026-08-12T00:00:00+00:00", "kind": "upload_new",
                           "path": f"f-{n:06}.txt"}) for n in range(12000)]
    path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    assert path.stat().st_size > MAX_HISTORY_BYTES

    trim_if_large(tmp_path)

    remaining = read(tmp_path)
    assert len(remaining) == 6000
    assert remaining[0]["path"] == "f-011999.txt"      # the newest survives
    assert remaining[-1]["path"] == "f-006000.txt"     # the oldest half is gone
