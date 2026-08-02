from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath

# Local mtime and Drive's modifiedTime come from different clocks; anything
# closer than this counts as "same time" -> no winner, keep both.
TIE_WINDOW_SECONDS = 5

# Actions that carry a change FROM local TO Drive.
# `foldrive push` executes exactly these; `pull` ignores them.
UPLOAD_KINDS = {
    "upload_new",       # file exists locally, not in Drive        -> create it in Drive
    "upload_changed",   # local copy edited since last sync        -> overwrite Drive's copy
    "trash_remote",     # file deleted locally                     -> move Drive's copy to trash
}

# Actions that carry a change FROM Drive TO local.
# `foldrive pull` executes exactly these; `push` ignores them.
DOWNLOAD_KINDS = {
    "download_new",     # file exists in Drive, not locally        -> create it on disk
    "download_changed", # Drive's copy edited since last sync      -> overwrite the local file
    "recycle_local",    # file deleted in Drive                    -> send local copy to Recycle Bin
}


@dataclass
class Action:
    kind: str
    relpath: str
    reason: str
    winner: str = ""  # conflicts only: "local", "drive", or "" for a tie


def drive_time_to_epoch(drive_modified_time):
    """Drive sends RFC-3339 text ('2026-07-31T10:00:00.000Z'); mtimes are floats."""
    if not drive_modified_time:
        return None
    return datetime.fromisoformat(
        drive_modified_time.replace("Z", "+00:00")
    ).timestamp()


def decide_conflict_winner(local_entry, remote_entry):
    """Newest wins; too close to call means no winner and both copies are kept."""
    remote_epoch = drive_time_to_epoch(remote_entry.get("modified"))
    local_epoch = local_entry.get("mtime")
    if remote_epoch is None or local_epoch is None:
        return ""
    if abs(local_epoch - remote_epoch) <= TIE_WINDOW_SECONDS:
        return ""
    return "local" if local_epoch > remote_epoch else "drive"


def conflict_copy_name(relpath, side, taken_names=()):
    """'notes.docx' + 'local' -> 'notes (local copy).docx', numbered if taken."""
    path = PurePosixPath(relpath)
    parent = str(path.parent) if str(path.parent) != "." else ""

    def build(label):
        name = f"{path.stem} ({label}){path.suffix}"
        return f"{parent}/{name}" if parent else name

    candidate = build(f"{side} copy")
    counter = 2
    while candidate in taken_names:
        candidate = build(f"{side} copy {counter}")
        counter += 1
    return candidate


def classify(local_files, remote_files, snapshot_files):
    actions = []
    all_relative_paths = sorted(
        set(local_files) | set(remote_files) | set(snapshot_files)
    )

    for relative_path in all_relative_paths:
        local_entry = local_files.get(relative_path)
        remote_entry = remote_files.get(relative_path)
        snapshot_entry = snapshot_files.get(relative_path)

        in_local = local_entry is not None
        in_remote = remote_entry is not None
        in_snapshot = snapshot_entry is not None

        local_changed = in_local and in_snapshot and local_entry["md5"] != snapshot_entry.get("md5")
        remote_changed = in_remote and in_snapshot and remote_entry["md5"] != snapshot_entry.get("md5")


        if not in_snapshot:
            if in_local and not in_remote:
                actions.append(Action("upload_new", relative_path, "new local file"))
            elif in_remote and not in_local:
                actions.append(Action("download_new", relative_path, "new file in Drive"))
            elif local_entry["md5"] == remote_entry["md5"]:
                actions.append(Action("link", relative_path, "identical on both sides"))
            else:
                actions.append(Action(
                    "conflict", relative_path,
                    "exists on both sides with different content",
                    decide_conflict_winner(local_entry, remote_entry),
                ))
        elif in_local and in_remote:
            if local_changed and remote_changed:
                actions.append(Action(
                    "conflict", relative_path,
                    "changed locally and in Drive",
                    decide_conflict_winner(local_entry, remote_entry),
                ))
            elif local_changed:
                actions.append(Action("upload_changed", relative_path, "changed locally"))
            elif remote_changed:
                actions.append(Action("download_changed", relative_path, "changed in Drive"))
        elif in_remote and not in_local:
            if remote_changed:
                actions.append(Action("download_new", relative_path, "deleted locally but changed in Drive"))
            else:
                actions.append(Action("trash_remote", relative_path, "deleted locally"))
        elif in_local and not in_remote:
            if local_changed:
                actions.append(Action("upload_new", relative_path, "deleted in Drive but changed locally"))
            else:
                actions.append(Action("recycle_local", relative_path, "deleted in Drive"))
        else:
            actions.append(Action("forget", relative_path, "gone from both sides"))

    return actions


def downgrade_for_first_sync(actions):
    """First sync must never delete: turn deletions into links/noops."""
    safe_actions = []
    for action in actions:
        if action.kind == "trash_remote":
            safe_actions.append(Action("upload_new", action.relpath, "first sync: keeping local file"))
        elif action.kind == "recycle_local":
            safe_actions.append(Action("download_new", action.relpath, "first sync: keeping Drive file"))
        elif action.kind == "forget":
            continue
        else:
            safe_actions.append(action)
    return safe_actions

















