"""Randomized correctness tests for the sync engine.

These are property tests, not example tests: each generates random situations and
asserts an invariant that must hold for every one of them.

    convergence   after syncing, both sides hold byte-identical trees
    idempotency   a second sync of an unchanged pair does no work
    no data loss  a conflict never discards either version
    crash safety  a killed sync redoes at most SAVE_EVERY-1 files

Trial counts are modest by default so `pytest` stays fast. Raise them for a real
soak run:

    FOLDRIVE_FUZZ_TRIALS=1000 pytest tests/test_fuzz.py -v
"""

import os
import random

import pytest

from foldrive import drive, engine, executor, scanner, state

from ..helpers.fake_drive import FakeDrive, install

# Slow by design: every test here is parametrized over SCALE trials. PR runs use
# `-m "not slow"`; the nightly job raises FOLDRIVE_FUZZ_TRIALS and runs only these.
pytestmark = pytest.mark.slow

# foldrive's own files are ignored in real use; the tests must do the same, or the
# harness syncs state.json into the fake Drive and nothing converges.
IGNORE = [".foldrive/", ".googledrive.json"]

SCALE = int(os.environ.get("FOLDRIVE_FUZZ_TRIALS", "50"))


def sync(folder, current_state):
    """One pull-then-push cycle, the same order `foldrive sync` uses."""
    local_files = scanner.scan(folder, IGNORE, current_state["files"])
    remote_files, remote_folders, _ = drive.list_tree(None, "root")
    current_state["folders"].update(remote_folders)

    actions = engine.classify(local_files, remote_files, current_state["files"])
    if not current_state["files"]:
        actions = engine.downgrade_for_first_sync(actions)

    pulls = [a for a in actions
             if a.kind in engine.DOWNLOAD_KINDS or a.kind in ("link", "forget")]
    conflicts = [a for a in actions if a.kind in ("conflict", "conflict_doc")]

    executor.pull(None, folder, current_state, pulls, local_files, remote_files)
    if conflicts:
        choices = executor.collect_conflict_choices(
            conflicts, local_files, remote_files, interactive=False,
            overrides={}, default_choice="keep_both")
        executor.apply_conflict_choices(None, folder, "root", current_state,
                                        choices, local_files, remote_files)

    local_files = scanner.scan(folder, IGNORE, current_state["files"])
    remote_files, _, _ = drive.list_tree(None, "root")
    actions = engine.classify(local_files, remote_files, current_state["files"])
    pushes = [a for a in actions
              if a.kind in engine.UPLOAD_KINDS or a.kind in ("link", "forget")]
    executor.push(None, folder, "root", current_state, pushes,
                  local_files, remote_files)


def pending(folder, current_state):
    local_files = scanner.scan(folder, IGNORE, current_state["files"])
    remote_files, _, _ = drive.list_tree(None, "root")
    actions = engine.classify(local_files, remote_files, current_state["files"])
    return [a for a in actions if a.kind not in ("link", "forget")]


def local_contents(folder):
    return {path.relative_to(folder).as_posix(): path.read_bytes()
            for path in folder.rglob("*")
            if path.is_file() and ".foldrive" not in path.parts}


@pytest.mark.parametrize("trial", range(SCALE))
def test_convergence_after_random_mutations(tmp_path, monkeypatch, trial):
    """Random edits/deletes on both sides must converge to identical trees."""
    random.seed(trial)
    fake = FakeDrive()
    install(fake, monkeypatch)

    names = [f"file-{n}.txt" for n in range(6)]
    for name in names:
        content = f"base {name}".encode()
        (tmp_path / name).write_bytes(content)
        fake.put(name, content)

    current_state = {"files": {}, "folders": {}}
    sync(tmp_path, current_state)

    for name in names:
        choice = random.choice(["none", "edit_local", "edit_remote",
                                "delete_local", "delete_remote", "edit_both"])
        if choice == "edit_local":
            (tmp_path / name).write_bytes(f"L{random.random()}".encode())
        elif choice == "edit_remote":
            fake.put(name, f"R{random.random()}".encode())
        elif choice == "delete_local":
            (tmp_path / name).unlink(missing_ok=True)
        elif choice == "delete_remote":
            fake.files.pop(name, None)
        elif choice == "edit_both":
            (tmp_path / name).write_bytes(f"L{random.random()}".encode())
            fake.put(name, f"R{random.random()}".encode())

    sync(tmp_path, current_state)
    sync(tmp_path, current_state)          # settle conflict copies

    assert local_contents(tmp_path) == fake.contents()


@pytest.mark.parametrize("trial", range(SCALE))
def test_second_sync_does_nothing(tmp_path, monkeypatch, trial):
    """Idempotency: syncing an already-synced pair must produce no actions."""
    random.seed(1000 + trial)
    fake = FakeDrive()
    install(fake, monkeypatch)

    for n in range(random.randint(1, 25)):
        (tmp_path / f"local-{n}.txt").write_text(f"local {n} {random.random()}")
    for n in range(random.randint(0, 15)):
        fake.put(f"remote-{n}.txt", f"remote {n} {random.random()}".encode())

    current_state = {"files": {}, "folders": {}}
    sync(tmp_path, current_state)

    assert pending(tmp_path, current_state) == []


@pytest.mark.parametrize("trial", range(SCALE))
def test_conflict_never_loses_either_version(tmp_path, monkeypatch, trial):
    """Both versions of a conflicted file must survive somewhere."""
    random.seed(2000 + trial)
    fake = FakeDrive()
    install(fake, monkeypatch)

    name = "contested.txt"
    (tmp_path / name).write_bytes(b"base")
    fake.put(name, b"base")
    current_state = {"files": {}, "folders": {}}
    sync(tmp_path, current_state)

    local_version = f"LOCAL-{random.random()}".encode()
    remote_version = f"REMOTE-{random.random()}".encode()
    (tmp_path / name).write_bytes(local_version)
    fake.put(name, remote_version)

    sync(tmp_path, current_state)
    sync(tmp_path, current_state)

    everywhere = list(local_contents(tmp_path).values()) + list(fake.contents().values())
    assert local_version in everywhere
    assert remote_version in everywhere


@pytest.mark.parametrize("trial", range(min(SCALE, 30)))
def test_crash_rework_stays_within_checkpoint_bound(tmp_path, monkeypatch, trial):
    """A killed sync must redo at most SAVE_EVERY-1 files on restart.

    Only what reached disk counts - the dead process's memory proves nothing.
    """
    random.seed(3000 + trial)
    fake = FakeDrive()
    install(fake, monkeypatch)

    file_count = 60
    for n in range(file_count):
        (tmp_path / f"f-{n:03}.bin").write_bytes(f"content-{n}".encode())

    kill_at = random.randint(1, file_count)
    counter = {"n": 0}
    real_upload = fake.upload

    def killing_upload(service, local_path, parent_id, name):
        counter["n"] += 1
        if counter["n"] == kill_at:
            raise BaseException("simulated process kill")
        return real_upload(service, local_path, parent_id, name)

    monkeypatch.setattr(drive, "upload", killing_upload)

    current_state = {"files": {}, "folders": {}}
    local_files = scanner.scan(tmp_path, IGNORE, {})
    remote_files, _, _ = drive.list_tree(None, "root")
    actions = engine.classify(local_files, remote_files, {})
    try:
        executor.push(None, tmp_path, "root", current_state, actions,
                      local_files, remote_files)
    except BaseException:
        pass

    survived = len(state.load_state(tmp_path)["files"])
    redone = (kill_at - 1) - survived
    assert 0 <= redone <= executor.SAVE_EVERY - 1
