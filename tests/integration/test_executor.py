"""The executor against a FakeDrive: what actually moves, and what gets counted.

Everything here goes through the real `executor` code path. Only `drive.*` is
replaced, so the snapshot bookkeeping, the checkpointing and the conflict
choreography are the production ones.
"""

import pytest

from foldrive import drive, engine, executor, scanner, state
from foldrive.engine import Action

IGNORE = [".foldrive/", ".googledrive.json"]


def write(folder, relpath, text):
    path = folder / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def plan(folder, current_state):
    """Scan both sides and classify, the way a command does."""
    local_files = scanner.scan(folder, IGNORE, current_state["files"])
    remote_files, remote_folders, _ = drive.list_tree(None, "root")
    current_state["folders"].update(remote_folders)
    actions = engine.classify(local_files, remote_files, current_state["files"])
    return actions, local_files, remote_files


def push(folder, current_state, actions, local_files, remote_files):
    return executor.push(None, folder, "root", current_state, actions,
                         local_files, remote_files)


def pull(folder, current_state, actions, local_files, remote_files):
    return executor.pull(None, folder, current_state, actions,
                         local_files, remote_files)


# --- push counters -----------------------------------------------------------

def test_push_counts_a_new_upload(tmp_path, fake_drive, empty_state):
    write(tmp_path, "a.txt", "hello")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = push(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary == {"uploaded": 1, "updated": 0, "trashed": 0, "linked": 0, "failed": 0}
    assert fake_drive.contents() == {"a.txt": b"hello"}


def test_push_counts_an_update_separately_from_an_upload(tmp_path, fake_drive, empty_state):
    write(tmp_path, "a.txt", "v1")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    write(tmp_path, "a.txt", "v2 is longer")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = push(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary["updated"] == 1
    assert summary["uploaded"] == 0
    assert fake_drive.contents()["a.txt"] == b"v2 is longer"


def test_push_counts_a_trash(tmp_path, fake_drive, empty_state):
    write(tmp_path, "a.txt", "hello")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    (tmp_path / "a.txt").unlink()
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = push(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary["trashed"] == 1
    assert fake_drive.contents() == {}
    assert "a.txt" not in empty_state["files"]


def test_push_counts_a_link_without_transferring(tmp_path, fake_drive, empty_state):
    """Identical on both sides: adopt it into the snapshot, move no bytes."""
    write(tmp_path, "a.txt", "same")
    fake_drive.put("a.txt", b"same")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = push(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary == {"uploaded": 0, "updated": 0, "trashed": 0, "linked": 1, "failed": 0}
    assert empty_state["files"]["a.txt"]["drive_file_id"] == fake_drive.files["a.txt"]["id"]


def test_push_counts_a_failure_and_keeps_going(tmp_path, fake_drive, empty_state, monkeypatch):
    """One locked or vanished file must not stop the rest of the run."""
    for name in ("a.txt", "b.txt", "c.txt"):
        write(tmp_path, name, name)

    real_upload = fake_drive.upload

    def upload_that_fails_on_b(service, local_path, parent_id, name):
        if name == "b.txt":
            raise OSError("file is locked by another process")
        return real_upload(service, local_path, parent_id, name)

    monkeypatch.setattr(drive, "upload", upload_that_fails_on_b)

    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = push(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary["uploaded"] == 2
    assert summary["failed"] == 1
    assert set(fake_drive.contents()) == {"a.txt", "c.txt"}


def test_push_creates_the_drive_folders_it_needs(tmp_path, fake_drive, empty_state):
    write(tmp_path, "notes/sem7/cn.txt", "deep")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    assert "notes/sem7/cn.txt" in fake_drive.contents()
    assert "notes" in empty_state["folders"]
    assert "notes/sem7" in empty_state["folders"]


def test_push_records_both_fingerprints_in_the_snapshot(tmp_path, fake_drive, empty_state):
    write(tmp_path, "a.txt", "hello")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    entry = empty_state["files"]["a.txt"]
    assert entry["md5"] == local_files["a.txt"]["md5"]
    assert entry["size"] == 5
    assert entry["drive_file_id"] == fake_drive.files["a.txt"]["id"]
    assert entry["drive_modified"] == fake_drive.files["a.txt"]["modified"]


# --- pull counters -----------------------------------------------------------

def test_pull_counts_a_download(tmp_path, fake_drive, empty_state):
    fake_drive.put("a.txt", b"from drive")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = pull(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary == {"downloaded": 1, "updated": 0, "recycled": 0,
                       "linked": 0, "failed": 0}
    assert (tmp_path / "a.txt").read_bytes() == b"from drive"


def test_pull_counts_an_update_separately(tmp_path, fake_drive, empty_state):
    fake_drive.put("a.txt", b"v1")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)

    fake_drive.put("a.txt", b"v2 from drive")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = pull(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary["updated"] == 1
    assert summary["downloaded"] == 0
    assert (tmp_path / "a.txt").read_bytes() == b"v2 from drive"


def test_pull_counts_a_recycle(tmp_path, fake_drive, empty_state):
    fake_drive.put("a.txt", b"hello")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)

    fake_drive.files.pop("a.txt")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = pull(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary["recycled"] == 1
    assert not (tmp_path / "a.txt").exists()
    assert "a.txt" not in empty_state["files"]


def test_pull_creates_the_local_directories_it_needs(tmp_path, fake_drive, empty_state):
    fake_drive.put("notes/sem7/cn.txt", b"deep")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)

    assert (tmp_path / "notes" / "sem7" / "cn.txt").read_bytes() == b"deep"


def test_pull_counts_a_failure_and_keeps_going(tmp_path, fake_drive, empty_state, monkeypatch):
    for name in ("a.txt", "b.txt", "c.txt"):
        fake_drive.put(name, name.encode())

    real_download = fake_drive.download

    def download_that_fails_on_b(service, file_id, destination_path):
        if destination_path.name == "b.txt":
            raise OSError("connection reset")
        return real_download(service, file_id, destination_path)

    monkeypatch.setattr(drive, "download", download_that_fails_on_b)

    actions, local_files, remote_files = plan(tmp_path, empty_state)
    summary = pull(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary["downloaded"] == 2
    assert summary["failed"] == 1


# --- checkpointing -----------------------------------------------------------

def test_the_snapshot_is_saved_every_save_every_transfers(tmp_path, fake_drive,
                                                          empty_state, monkeypatch):
    """The bound the crash test relies on: a killed run redoes at most 24 files."""
    saved_sizes = []
    real_save = state.save_state

    def spy(folder, current_state):
        saved_sizes.append(len(current_state["files"]))
        return real_save(folder, current_state)

    monkeypatch.setattr(executor.state, "save_state", spy)

    for n in range(executor.SAVE_EVERY * 2 + 3):
        write(tmp_path, f"f-{n:03}.txt", str(n))

    actions, local_files, remote_files = plan(tmp_path, empty_state)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    assert saved_sizes == [executor.SAVE_EVERY, executor.SAVE_EVERY * 2]


def test_no_checkpoint_when_there_are_too_few_transfers(tmp_path, fake_drive,
                                                        empty_state, monkeypatch):
    saves = []
    monkeypatch.setattr(executor.state, "save_state",
                        lambda folder, current: saves.append(1))

    for n in range(executor.SAVE_EVERY - 1):
        write(tmp_path, f"f-{n:03}.txt", str(n))

    actions, local_files, remote_files = plan(tmp_path, empty_state)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    assert saves == []


def test_links_do_not_count_toward_the_checkpoint(tmp_path, fake_drive,
                                                  empty_state, monkeypatch):
    """`link` only touches the snapshot in memory, so counting it would save
    on a run that moved no bytes at all."""
    saves = []
    monkeypatch.setattr(executor.state, "save_state",
                        lambda folder, current: saves.append(1))

    for n in range(executor.SAVE_EVERY + 5):
        write(tmp_path, f"f-{n:03}.txt", str(n))
        fake_drive.put(f"f-{n:03}.txt", str(n).encode())

    actions, local_files, remote_files = plan(tmp_path, empty_state)
    assert all(action.kind == "link" for action in actions)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    assert saves == []


# --- conflict resolution, all four choices -----------------------------------

def conflicted(tmp_path, fake_drive, empty_state, local_text, drive_text):
    """One file, different content on each side, already linked in the snapshot."""
    write(tmp_path, "shared.txt", "base")
    fake_drive.put("shared.txt", b"base")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    write(tmp_path, "shared.txt", local_text)
    fake_drive.put("shared.txt", drive_text.encode())
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    conflicts = [a for a in actions if a.kind == "conflict"]
    assert len(conflicts) == 1
    return conflicts[0], local_files, remote_files


def resolve(tmp_path, empty_state, action, local_files, remote_files, choice):
    return executor.resolve_conflict(None, tmp_path, "root", empty_state, action,
                                     local_files, remote_files, choice)


def test_conflict_skip_changes_nothing(tmp_path, fake_drive, empty_state):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    note = resolve(tmp_path, empty_state, action, local_files, remote_files, "skip")

    assert "skipped" in note
    assert (tmp_path / "shared.txt").read_text() == "LOCAL"
    assert fake_drive.contents()["shared.txt"] == b"DRIVE"


def test_conflict_local_overwrites_drive(tmp_path, fake_drive, empty_state):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    note = resolve(tmp_path, empty_state, action, local_files, remote_files, "local")

    assert "local kept" in note
    assert (tmp_path / "shared.txt").read_text() == "LOCAL"
    assert fake_drive.contents()["shared.txt"] == b"LOCAL"
    assert list(tmp_path.glob("*copy*")) == []


def test_conflict_drive_overwrites_local(tmp_path, fake_drive, empty_state):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    note = resolve(tmp_path, empty_state, action, local_files, remote_files, "drive")

    assert "Drive kept" in note
    assert (tmp_path / "shared.txt").read_text() == "DRIVE"
    assert fake_drive.contents()["shared.txt"] == b"DRIVE"
    assert list(tmp_path.glob("*copy*")) == []


def test_keep_both_with_a_local_winner_keeps_the_name_local(tmp_path, fake_drive,
                                                            empty_state):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    action = Action(action.kind, action.relpath, action.reason, winner="local")
    note = resolve(tmp_path, empty_state, action, local_files, remote_files, "keep_both")

    assert "kept both" in note
    assert (tmp_path / "shared.txt").read_text() == "LOCAL"
    assert (tmp_path / "shared (drive copy).txt").read_text() == "DRIVE"
    assert fake_drive.contents()["shared.txt"] == b"LOCAL"
    assert fake_drive.contents()["shared (drive copy).txt"] == b"DRIVE"


def test_keep_both_with_a_drive_winner_keeps_the_name_for_drive(tmp_path, fake_drive,
                                                                empty_state):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    action = Action(action.kind, action.relpath, action.reason, winner="drive")
    resolve(tmp_path, empty_state, action, local_files, remote_files, "keep_both")

    assert (tmp_path / "shared.txt").read_text() == "DRIVE"
    assert (tmp_path / "shared (local copy).txt").read_text() == "LOCAL"
    assert fake_drive.contents()["shared.txt"] == b"DRIVE"
    assert fake_drive.contents()["shared (local copy).txt"] == b"LOCAL"


def test_a_tie_gives_the_original_name_to_neither_side(tmp_path, fake_drive, empty_state):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    action = Action(action.kind, action.relpath, action.reason, winner="")
    note = resolve(tmp_path, empty_state, action, local_files, remote_files, "keep_both")

    assert "tie" in note
    assert not (tmp_path / "shared.txt").exists()
    assert (tmp_path / "shared (local copy).txt").read_text() == "LOCAL"
    assert (tmp_path / "shared (drive copy).txt").read_text() == "DRIVE"
    assert "shared.txt" not in empty_state["files"]


@pytest.mark.parametrize("winner", ["local", "drive", ""])
def test_keep_both_never_loses_either_version(tmp_path, fake_drive, empty_state, winner):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    action = Action(action.kind, action.relpath, action.reason, winner=winner)
    resolve(tmp_path, empty_state, action, local_files, remote_files, "keep_both")

    everywhere = [path.read_bytes() for path in tmp_path.rglob("*")
                  if path.is_file() and ".foldrive" not in path.parts]
    everywhere += list(fake_drive.contents().values())
    assert b"LOCAL" in everywhere
    assert b"DRIVE" in everywhere


def test_a_conflict_copy_name_that_is_already_taken_gets_numbered(tmp_path, fake_drive,
                                                                  empty_state):
    """The obvious name already exists on one side, so the copy must not
    overwrite it."""
    write(tmp_path, "shared.txt", "base")
    write(tmp_path, "shared (drive copy).txt", "AN EARLIER COPY")
    fake_drive.put("shared.txt", b"base")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    push(tmp_path, empty_state, actions, local_files, remote_files)

    write(tmp_path, "shared.txt", "LOCAL")
    fake_drive.put("shared.txt", b"DRIVE")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    action = [a for a in actions if a.kind == "conflict"][0]
    action = Action(action.kind, action.relpath, action.reason, winner="local")

    resolve(tmp_path, empty_state, action, local_files, remote_files, "keep_both")

    assert (tmp_path / "shared (drive copy).txt").read_text() == "AN EARLIER COPY"
    assert (tmp_path / "shared (drive copy 2).txt").read_text() == "DRIVE"


# --- collect / apply ---------------------------------------------------------

def test_choices_are_collected_before_anything_transfers(tmp_path, fake_drive,
                                                         empty_state):
    """collect_conflict_choices is pure: it must not touch Drive or the disk."""
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    before = dict(fake_drive.contents())

    choices = executor.collect_conflict_choices(
        [action], local_files, remote_files, interactive=False,
        overrides={}, default_choice="keep_both")

    assert choices == [(action, "keep_both")]
    assert fake_drive.contents() == before
    assert (tmp_path / "shared.txt").read_text() == "LOCAL"


def test_a_per_file_override_beats_the_default(tmp_path, fake_drive, empty_state):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    choices = executor.collect_conflict_choices(
        [action], local_files, remote_files, interactive=False,
        overrides={"shared.txt": "local"}, default_choice="keep_both")

    assert choices == [(action, "local")]


def test_apply_saves_the_snapshot_after_every_conflict(tmp_path, fake_drive,
                                                       empty_state, monkeypatch):
    """One conflict is three or four transfers, so the write costs nothing next
    to redoing it."""
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")
    saves = []
    monkeypatch.setattr(executor.state, "save_state",
                        lambda folder, current: saves.append(1))

    executor.apply_conflict_choices(None, tmp_path, "root", empty_state,
                                    [(action, "local")], local_files, remote_files)
    assert len(saves) == 1


def test_a_failing_conflict_is_noted_and_the_rest_continue(tmp_path, fake_drive,
                                                           empty_state, monkeypatch):
    action, local_files, remote_files = conflicted(
        tmp_path, fake_drive, empty_state, "LOCAL", "DRIVE")

    def update_that_fails(service, file_id, local_path):
        raise OSError("connection reset")

    monkeypatch.setattr(drive, "update", update_that_fails)
    notes = executor.apply_conflict_choices(None, tmp_path, "root", empty_state,
                                            [(action, "local")], local_files,
                                            remote_files)
    assert "failed shared.txt" in notes[0]


# --- Google native files -----------------------------------------------------

def test_a_doc_downloads_as_its_export_format(tmp_path, fake_drive, empty_state):
    relpath = fake_drive.put_doc("notes", b"DOC BODY", native_type="docs")
    assert relpath == "notes.docx"

    actions, local_files, remote_files = plan(tmp_path, empty_state)
    assert [a.kind for a in actions] == ["download_new_doc"]
    summary = pull(tmp_path, empty_state, actions, local_files, remote_files)

    assert summary["downloaded"] == 1
    assert (tmp_path / "notes.docx").read_bytes().startswith(b"DOC BODY")


def test_a_docs_snapshot_entry_compares_on_modified_time_not_md5(tmp_path, fake_drive,
                                                                 empty_state):
    fake_drive.put_doc("notes", b"DOC BODY")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)

    entry = empty_state["files"]["notes.docx"]
    assert entry["md5"] is None
    assert entry["drive_modified"] == fake_drive.docs["notes.docx"]["modified"]


def test_an_untouched_doc_is_not_downloaded_again(tmp_path, fake_drive, empty_state):
    """Exports are not byte-stable, so an md5 comparison would re-download this
    file on every single run. modifiedTime is the only usable signal."""
    fake_drive.put_doc("notes", b"DOC BODY")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)

    actions, _local, _remote = plan(tmp_path, empty_state)
    assert [a for a in actions if a.kind != "link"] == []


def test_an_edited_doc_downloads_again(tmp_path, fake_drive, empty_state):
    fake_drive.put_doc("notes", b"v1")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)

    fake_drive.put_doc("notes", b"v2")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    assert [a.kind for a in actions] == ["download_changed_doc"]

    pull(tmp_path, empty_state, actions, local_files, remote_files)
    assert (tmp_path / "notes.docx").read_bytes().startswith(b"v2")


def test_a_local_edit_uploads_back_into_the_same_doc(tmp_path, fake_drive, empty_state):
    """Updating by id is what makes this safe - it can never create a second file."""
    fake_drive.put_doc("notes", b"v1")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)
    doc_id = fake_drive.docs["notes.docx"]["id"]

    write(tmp_path, "notes.docx", "EDITED LOCALLY")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    assert [a.kind for a in actions] == ["upload_changed_doc"]

    summary = push(tmp_path, empty_state, actions, local_files, remote_files)
    assert summary["updated"] == 1
    assert fake_drive.docs["notes.docx"]["id"] == doc_id
    assert fake_drive.docs["notes.docx"]["content"] == b"EDITED LOCALLY"


def test_download_keeping_the_local_edit_renames_it_aside_first(tmp_path, fake_drive,
                                                                empty_state):
    fake_drive.put_doc("notes", b"v1")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)

    write(tmp_path, "notes.docx", "MY LOCAL EDIT")
    fake_drive.put_doc("notes", b"DRIVE EDIT")
    _actions, local_files, remote_files = plan(tmp_path, empty_state)

    keep_local = Action("download_changed_doc_keep_local", "notes.docx",
                        "changed both sides")
    pull(tmp_path, empty_state, [keep_local], local_files, remote_files)

    assert (tmp_path / "notes (local copy).docx").read_text() == "MY LOCAL EDIT"
    assert (tmp_path / "notes.docx").read_bytes().startswith(b"DRIVE EDIT")


def test_upload_keeping_drives_version_saves_it_aside_first(tmp_path, fake_drive,
                                                            empty_state):
    fake_drive.put_doc("notes", b"v1")
    actions, local_files, remote_files = plan(tmp_path, empty_state)
    pull(tmp_path, empty_state, actions, local_files, remote_files)

    write(tmp_path, "notes.docx", "MY LOCAL EDIT")
    fake_drive.put_doc("notes", b"DRIVE EDIT")
    _actions, local_files, remote_files = plan(tmp_path, empty_state)

    keep_drive = Action("upload_changed_doc_keep_drive", "notes.docx",
                        "changed both sides")
    push(tmp_path, empty_state, [keep_drive], local_files, remote_files)

    assert (tmp_path / "notes (drive copy).docx").read_bytes().startswith(b"DRIVE EDIT")
    assert fake_drive.docs["notes.docx"]["content"] == b"MY LOCAL EDIT"


def test_sheets_and_slides_get_their_own_extensions(tmp_path, fake_drive, empty_state):
    assert fake_drive.put_doc("budget", b"x", native_type="sheets") == "budget.xlsx"
    assert fake_drive.put_doc("deck", b"y", native_type="slides") == "deck.pptx"

    _actions, _local, remote_files = plan(tmp_path, empty_state)
    assert remote_files["budget.xlsx"]["native_type"] == "sheets"
    assert remote_files["deck.pptx"]["native_type"] == "slides"
