"""The safety layers that sit between classify() and the executor.

classify() decides what changed; these four decide what is allowed to happen as
a result. They are the last thing standing between a bug on one side and a
folder full of deleted files, and each one is pure — dicts and Actions in,
Actions out.
"""

import pytest

from foldrive.engine import (
    Action,
    apply_delete_policy,
    apply_google_native_mode,
    downgrade_for_first_sync,
    mass_delete_check,
)

TRASH_BOTH = {"local": "trash", "drive": "trash"}


def deletions(kind, count):
    return [Action(kind, f"f-{n}.txt", "deleted") for n in range(count)]


def kinds(actions):
    return [action.kind for action in actions]


def native(native_type, modified="2026-08-12T00:00:00.000Z"):
    return {
        "id": "d1", "size": 0, "md5": None, "modified": modified,
        "is_google_native": True,
        "native_mime": f"application/vnd.google-apps.{native_type}",
        "export_mime": "application/vnd.openxmlformats-officedocument.x",
        "native_type": native_type,
    }


# --- apply_delete_policy -----------------------------------------------------

def test_trash_on_both_sides_keeps_every_deletion():
    actions = deletions("trash_remote", 2) + deletions("recycle_local", 2)
    kept, notes = apply_delete_policy(actions, TRASH_BOTH)
    assert len(kept) == 4
    assert notes == []


def test_never_delete_on_drive_drops_only_the_drive_deletions():
    """delete_policy names the side deleted FROM: "drive" governs trash_remote."""
    actions = deletions("trash_remote", 3) + deletions("recycle_local", 2)
    kept, notes = apply_delete_policy(actions, {"local": "trash", "drive": "never_delete"})
    assert kinds(kept) == ["recycle_local"] * 2
    assert len(notes) == 1
    assert "3 file(s) deleted locally are kept in Drive" in notes[0]


def test_never_delete_on_local_drops_only_the_local_deletions():
    actions = deletions("trash_remote", 3) + deletions("recycle_local", 2)
    kept, notes = apply_delete_policy(actions, {"local": "never_delete", "drive": "trash"})
    assert kinds(kept) == ["trash_remote"] * 3
    assert len(notes) == 1
    assert "2 file(s) deleted in Drive are kept locally" in notes[0]


def test_never_delete_on_both_sides_drops_everything_and_notes_both():
    actions = deletions("trash_remote", 1) + deletions("recycle_local", 1)
    kept, notes = apply_delete_policy(
        actions, {"local": "never_delete", "drive": "never_delete"}
    )
    assert kept == []
    assert len(notes) == 2


def test_delete_policy_never_touches_a_transfer():
    actions = [Action("upload_new", "a.txt", ""), Action("download_changed", "b.txt", "")]
    kept, notes = apply_delete_policy(
        actions, {"local": "never_delete", "drive": "never_delete"}
    )
    assert kept == actions
    assert notes == []


def test_delete_policy_preserves_order():
    actions = [
        Action("upload_new", "a.txt", ""),
        Action("trash_remote", "b.txt", ""),
        Action("download_new", "c.txt", ""),
    ]
    kept, _ = apply_delete_policy(actions, {"local": "trash", "drive": "never_delete"})
    assert [action.relpath for action in kept] == ["a.txt", "c.txt"]


# --- mass_delete_check -------------------------------------------------------
#
# Trips only when BOTH thresholds are crossed: at least `minimum_count` files and
# at least `max_percent` of that side. Either alone misfires — a percentage on a
# 4-file folder, a count on a 4000-file one.

def test_no_refusal_below_the_minimum_count():
    """9 of 10 is 90%, but 9 is under the minimum, so it is an ordinary cleanup."""
    actions = deletions("recycle_local", 9)
    assert mass_delete_check(actions, 10, 10, 25, 10) is None


def test_no_refusal_below_the_percentage():
    """20 files is over the minimum, but 20 of 4000 is 0.5% - routine."""
    actions = deletions("recycle_local", 20)
    assert mass_delete_check(actions, 4000, 4000, 25, 10) is None


def test_refuses_when_both_thresholds_are_crossed():
    actions = deletions("recycle_local", 30)
    message = mass_delete_check(actions, 100, 100, 25, 10)
    assert message is not None
    assert "30 of 100 local files" in message
    assert "the Recycle Bin" in message
    assert "--allow-mass-delete" in message


def test_refusal_names_drive_for_the_other_direction():
    actions = deletions("trash_remote", 30)
    message = mass_delete_check(actions, 100, 100, 25, 10)
    assert "30 of 100 Drive files" in message
    assert "Drive's trash" in message


def test_exactly_at_both_thresholds_refuses():
    """The comparisons are >= and >=, so the boundary itself trips the guard."""
    actions = deletions("recycle_local", 10)
    assert mass_delete_check(actions, 40, 40, 25, 10) is not None


def test_one_under_the_count_threshold_passes():
    actions = deletions("recycle_local", 9)
    assert mass_delete_check(actions, 36, 36, 25, 10) is None


def test_one_under_the_percent_threshold_passes():
    """24 of 100 is 24%, just under 25."""
    actions = deletions("recycle_local", 24)
    assert mass_delete_check(actions, 100, 100, 25, 10) is None


def test_zero_percent_disables_the_guard_entirely():
    actions = deletions("recycle_local", 500)
    assert mass_delete_check(actions, 500, 500, 0, 10) is None


def test_a_negative_percent_also_disables_it():
    actions = deletions("recycle_local", 500)
    assert mass_delete_check(actions, 500, 500, -1, 10) is None


def test_an_empty_side_cannot_trip_the_guard():
    """Nothing to divide by: 0 local files means no local deletion is possible."""
    actions = deletions("recycle_local", 30)
    assert mass_delete_check(actions, 0, 100, 25, 10) is None


def test_the_local_side_is_checked_before_the_drive_side():
    actions = deletions("recycle_local", 30) + deletions("trash_remote", 30)
    message = mass_delete_check(actions, 100, 100, 25, 10)
    assert "local files" in message


def test_a_run_with_no_deletions_is_never_refused():
    actions = [Action("upload_new", f"f-{n}.txt", "") for n in range(500)]
    assert mass_delete_check(actions, 500, 500, 25, 10) is None


# --- apply_google_native_mode ------------------------------------------------

def test_ordinary_files_pass_through_every_mode():
    """No native_type on the remote entry means the mode does not apply."""
    actions = [Action("upload_changed", "a.txt", ""), Action("download_new", "b.txt", "")]
    remote = {"a.txt": {"id": "1", "md5": "x"}, "b.txt": {"id": "2", "md5": "y"}}
    kept, notes = apply_google_native_mode(actions, remote, {"docs": "skip"})
    assert kept == actions
    assert notes == []


def test_a_file_missing_from_remote_passes_through():
    """upload_new has no remote entry at all - it must not be filtered out."""
    actions = [Action("upload_new", "new.txt", "")]
    kept, notes = apply_google_native_mode(actions, {}, {"docs": "skip"})
    assert kept == actions
    assert notes == []


@pytest.mark.parametrize("kind", [
    "download_new_doc", "download_changed_doc", "upload_changed_doc", "conflict_doc",
])
def test_skip_drops_every_doc_action_silently(kind):
    """skip is not a warning - the user asked for these to be left alone."""
    actions = [Action(kind, "notes.docx", "")]
    remote = {"notes.docx": native("docs")}
    kept, notes = apply_google_native_mode(actions, remote, {"docs": "skip"})
    assert kept == []
    assert notes == []


@pytest.mark.parametrize("kind", [
    "download_new_doc", "download_changed_doc", "upload_changed_doc",
])
def test_two_way_keeps_every_doc_action(kind):
    actions = [Action(kind, "notes.docx", "")]
    remote = {"notes.docx": native("docs")}
    kept, notes = apply_google_native_mode(actions, remote, {"docs": "two_way"})
    assert kinds(kept) == [kind]
    assert notes == []


@pytest.mark.parametrize("kind", ["download_new_doc", "download_changed_doc"])
def test_download_only_keeps_downloads(kind):
    actions = [Action(kind, "notes.docx", "")]
    remote = {"notes.docx": native("docs")}
    kept, notes = apply_google_native_mode(actions, remote, {"docs": "download_only"})
    assert kinds(kept) == [kind]
    assert notes == []


def test_download_only_notes_an_upload_instead_of_doing_it():
    """A footnote, not a pending action: there is nothing the user can do to
    clear it, so counting it would stop status ever saying "in sync" again."""
    actions = [Action("upload_changed_doc", "notes.docx", "")]
    remote = {"notes.docx": native("docs")}
    kept, notes = apply_google_native_mode(actions, remote, {"docs": "download_only"})
    assert kept == []
    assert len(notes) == 1
    assert "will never be uploaded" in notes[0]
    assert "notes.docx" in notes[0]


def test_download_only_resolves_a_doc_conflict_toward_drive():
    actions = [Action("conflict_doc", "notes.docx", "")]
    remote = {"notes.docx": native("docs")}
    kept, _ = apply_google_native_mode(actions, remote, {"docs": "download_only"})
    assert kinds(kept) == ["download_changed_doc_keep_local"]


@pytest.mark.parametrize("kind", ["upload_changed_doc"])
def test_upload_only_keeps_uploads(kind):
    actions = [Action(kind, "notes.docx", "")]
    remote = {"notes.docx": native("docs")}
    kept, notes = apply_google_native_mode(actions, remote, {"docs": "upload_only"})
    assert kinds(kept) == [kind]
    assert notes == []


@pytest.mark.parametrize("kind", ["download_new_doc", "download_changed_doc"])
def test_upload_only_notes_a_download_instead_of_doing_it(kind):
    actions = [Action(kind, "notes.docx", "")]
    remote = {"notes.docx": native("docs")}
    kept, notes = apply_google_native_mode(actions, remote, {"docs": "upload_only"})
    assert kept == []
    assert len(notes) == 1
    assert "will never be downloaded" in notes[0]


def test_upload_only_resolves_a_doc_conflict_toward_local():
    actions = [Action("conflict_doc", "notes.docx", "")]
    remote = {"notes.docx": native("docs")}
    kept, _ = apply_google_native_mode(actions, remote, {"docs": "upload_only"})
    assert kinds(kept) == ["upload_changed_doc_keep_drive"]


def test_each_native_type_follows_its_own_mode():
    """Sheets default to skip while Docs download: one run, two behaviours."""
    actions = [
        Action("download_new_doc", "notes.docx", ""),
        Action("download_new_doc", "budget.xlsx", ""),
        Action("download_new_doc", "deck.pptx", ""),
    ]
    remote = {
        "notes.docx": native("docs"),
        "budget.xlsx": native("sheets"),
        "deck.pptx": native("slides"),
    }
    modes = {"docs": "download_only", "sheets": "skip", "slides": "two_way"}
    kept, _ = apply_google_native_mode(actions, remote, modes)
    assert [action.relpath for action in kept] == ["notes.docx", "deck.pptx"]


def test_an_unconfigured_native_type_defaults_to_skip():
    actions = [Action("download_new_doc", "budget.xlsx", "")]
    remote = {"budget.xlsx": native("sheets")}
    kept, _ = apply_google_native_mode(actions, remote, {"docs": "two_way"})
    assert kept == []


# --- downgrade_for_first_sync ------------------------------------------------

def test_first_sync_turns_a_drive_trash_into_an_upload():
    actions = [Action("trash_remote", "a.txt", "deleted locally")]
    downgraded = downgrade_for_first_sync(actions)
    assert kinds(downgraded) == ["upload_new"]
    assert "first sync" in downgraded[0].reason


def test_first_sync_turns_a_local_recycle_into_a_download():
    actions = [Action("recycle_local", "a.txt", "deleted in Drive")]
    downgraded = downgrade_for_first_sync(actions)
    assert kinds(downgraded) == ["download_new"]


def test_first_sync_drops_forget():
    assert downgrade_for_first_sync([Action("forget", "a.txt", "")]) == []


def test_first_sync_leaves_transfers_alone():
    actions = [
        Action("upload_new", "a.txt", ""),
        Action("download_changed", "b.txt", ""),
        Action("conflict", "c.txt", "", winner="local"),
        Action("link", "d.txt", ""),
    ]
    assert downgrade_for_first_sync(actions) == actions


def test_first_sync_never_emits_a_deletion_for_any_input():
    """The whole point: a first sync merges two unknown trees and deletes nothing."""
    every_kind = [
        "upload_new", "upload_changed", "trash_remote",
        "download_new", "download_changed", "recycle_local",
        "download_new_doc", "download_changed_doc", "download_changed_doc_keep_local",
        "upload_changed_doc", "upload_changed_doc_keep_drive",
        "conflict", "conflict_doc", "link", "forget",
    ]
    actions = [Action(kind, f"{kind}.txt", "") for kind in every_kind]
    downgraded = downgrade_for_first_sync(actions)
    assert not any(action.kind in ("trash_remote", "recycle_local")
                   for action in downgraded)
