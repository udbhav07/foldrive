"""Local truth: what scan() sees, what it ignores, and what it refuses to guess."""

import os

import pytest

from foldrive import scanner
from foldrive.scanner import _split_patterns, compute_md5, scan


def write(folder, relpath, text="x"):
    path = folder / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- pattern splitting -------------------------------------------------------

def test_a_trailing_slash_makes_it_a_directory_pattern():
    directories, files = _split_patterns(["build/", "*.pyc"])
    assert directories == ["build"]
    assert files == ["*.pyc"]


def test_patterns_without_a_slash_are_file_patterns():
    directories, files = _split_patterns(["*.tmp", "desktop.ini"])
    assert directories == []
    assert files == ["*.tmp", "desktop.ini"]


# --- what gets scanned -------------------------------------------------------

def test_scan_returns_size_mtime_and_md5(tmp_path):
    write(tmp_path, "a.txt", "hello")
    entry = scan(tmp_path, [], {})["a.txt"]
    assert entry["size"] == 5
    assert entry["md5"] == compute_md5(tmp_path / "a.txt")
    assert entry["mtime"] == pytest.approx((tmp_path / "a.txt").stat().st_mtime)


def test_scan_uses_forward_slashes_for_nested_paths(tmp_path):
    write(tmp_path, "notes/sem7/cn.txt")
    assert "notes/sem7/cn.txt" in scan(tmp_path, [], {})


def test_an_empty_folder_scans_to_nothing(tmp_path):
    assert scan(tmp_path, [], {}) == {}


# --- ignoring ----------------------------------------------------------------

def test_a_directory_pattern_skips_the_whole_subtree(tmp_path):
    write(tmp_path, "keep.txt")
    write(tmp_path, "build/out.txt")
    write(tmp_path, "build/deep/deeper/out.txt")
    assert set(scan(tmp_path, ["build/"], {})) == {"keep.txt"}


def test_a_directory_pattern_does_not_ignore_a_file_of_that_name(tmp_path):
    """"build/" names a directory; a file called `build` is a different thing."""
    write(tmp_path, "build")
    assert set(scan(tmp_path, ["build/"], {})) == {"build"}


def test_a_file_pattern_matches_by_basename_at_any_depth(tmp_path):
    write(tmp_path, "a.tmp")
    write(tmp_path, "notes/b.tmp")
    write(tmp_path, "notes/c.txt")
    assert set(scan(tmp_path, ["*.tmp"], {})) == {"notes/c.txt"}


def test_a_file_pattern_can_match_the_whole_relative_path(tmp_path):
    """Matching only basenames would make "notes/*.txt" impossible to express."""
    write(tmp_path, "notes/scratch.txt")
    write(tmp_path, "other/scratch.txt")
    assert set(scan(tmp_path, ["notes/*.txt"], {})) == {"other/scratch.txt"}


def test_a_nested_pattern_does_not_match_the_same_name_elsewhere(tmp_path):
    write(tmp_path, "notes/keep.txt")
    write(tmp_path, "keep.txt")
    assert set(scan(tmp_path, ["notes/keep.txt"], {})) == {"keep.txt"}


def test_foldrives_own_files_are_ignorable(tmp_path):
    write(tmp_path, "a.txt")
    write(tmp_path, ".googledrive.json", "{}")
    write(tmp_path, ".foldrive/state.json", "{}")
    scanned = scan(tmp_path, [".foldrive/", ".googledrive.json"], {})
    assert set(scanned) == {"a.txt"}


# --- the md5 shortcut --------------------------------------------------------

def test_md5_is_reused_when_size_and_mtime_match(tmp_path):
    """The whole point of the snapshot: unchanged files are never re-read."""
    path = write(tmp_path, "a.txt", "hello")
    file_stat = path.stat()
    previous = {"a.txt": {"size": file_stat.st_size, "mtime": file_stat.st_mtime,
                          "md5": "trusted-from-the-snapshot"}}
    assert scan(tmp_path, [], previous)["a.txt"]["md5"] == "trusted-from-the-snapshot"


def test_md5_is_recomputed_when_the_mtime_moved(tmp_path):
    path = write(tmp_path, "a.txt", "hello")
    previous = {"a.txt": {"size": path.stat().st_size, "mtime": 1.0,
                          "md5": "stale"}}
    assert scan(tmp_path, [], previous)["a.txt"]["md5"] == compute_md5(path)


def test_md5_is_recomputed_when_the_size_moved(tmp_path):
    path = write(tmp_path, "a.txt", "hello")
    previous = {"a.txt": {"size": 999, "mtime": path.stat().st_mtime,
                          "md5": "stale"}}
    assert scan(tmp_path, [], previous)["a.txt"]["md5"] == compute_md5(path)


def test_md5_is_computed_for_a_file_the_snapshot_has_never_seen(tmp_path):
    path = write(tmp_path, "new.txt", "hello")
    assert scan(tmp_path, [], {})["new.txt"]["md5"] == compute_md5(path)


def test_compute_md5_reads_files_larger_than_one_chunk(tmp_path):
    import hashlib
    payload = b"z" * (scanner.HASH_CHUNK_SIZE * 2 + 17)
    path = tmp_path / "big.bin"
    path.write_bytes(payload)
    assert compute_md5(path) == hashlib.md5(payload).hexdigest()


# --- an unreadable directory -------------------------------------------------

def test_an_unreadable_directory_raises_instead_of_being_skipped(tmp_path, monkeypatch):
    """os.walk drops unreadable directories silently, and a missing file is
    indistinguishable from a deleted one - so foldrive would trash them in
    Drive. Refusing is the only safe answer."""
    def walk_that_fails(top, onerror=None, **kwargs):
        error = OSError(13, "Permission denied")
        error.filename = str(tmp_path / "locked")
        error.strerror = "Permission denied"
        onerror(error)
        yield str(tmp_path), [], []

    monkeypatch.setattr(os, "walk", walk_that_fails)
    with pytest.raises(SystemExit, match="Cannot read"):
        scan(tmp_path, [], {})


def test_the_refusal_names_the_directory(tmp_path, monkeypatch):
    def walk_that_fails(top, onerror=None, **kwargs):
        error = OSError(13, "Permission denied")
        error.filename = "/private/notes"
        error.strerror = "Permission denied"
        onerror(error)
        yield str(tmp_path), [], []

    monkeypatch.setattr(os, "walk", walk_that_fails)
    with pytest.raises(SystemExit, match="/private/notes"):
        scan(tmp_path, [], {})


def test_the_macos_refusal_explains_full_disk_access(tmp_path, monkeypatch):
    def walk_that_fails(top, onerror=None, **kwargs):
        error = OSError(1, "Operation not permitted")
        error.filename = "/Users/x/Desktop"
        error.strerror = "Operation not permitted"
        onerror(error)
        yield str(tmp_path), [], []

    monkeypatch.setattr(os, "walk", walk_that_fails)
    monkeypatch.setattr(scanner.sys, "platform", "darwin")
    with pytest.raises(SystemExit, match="Full Disk Access"):
        scan(tmp_path, [], {})


def test_a_file_that_vanishes_between_walk_and_stat_is_skipped(tmp_path, monkeypatch):
    """Not the same case: one file disappearing is normal, and the next run
    classifies it properly. It is a whole unreadable directory that is fatal."""
    write(tmp_path, "here.txt")
    write(tmp_path, "gone.txt")
    real_stat = scanner.Path.stat

    def stat_that_vanishes(self, *args, **kwargs):
        if self.name == "gone.txt":
            raise FileNotFoundError(2, "No such file")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(scanner.Path, "stat", stat_that_vanishes)
    assert set(scan(tmp_path, [], {})) == {"here.txt"}
