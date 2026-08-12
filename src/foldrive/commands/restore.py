"""Bring one file back from Drive.

Needed because a file can be present in Drive and absent locally while foldrive
considers the matter settled - most obviously under delete_policy "never_delete",
where a local deletion is deliberately not propagated and so never comes back.
Without this, the only fix was hand-editing state.json.
"""

import difflib
from pathlib import Path

from googleapiclient.errors import HttpError

from .. import auth, config, drive, history, state


def run(args):
    folder = config.find_config_root(Path.cwd())
    if folder is None:
        raise SystemExit("Not a foldrive folder. Run: foldrive init")

    folder_config = config.load_config(folder)
    current_state = state.load_state(folder)
    service = auth.get_service()

    try:
        remote_files, _remote_folders, _skipped = drive.list_tree(
            service, folder_config["drive_folder_id"]
        )
    except HttpError as api_error:
        raise SystemExit(f"Google Drive API error: {api_error.reason}")
    except OSError:
        raise SystemExit("Network error - are you connected to the internet?")

    wanted = args.path.replace("\\", "/").lstrip("./")
    remote_entry = remote_files.get(wanted)

    if remote_entry is None:
        # A wrong path is the likely mistake, so help rather than just refusing.
        # Substring match finds "notes/unit-3.pdf" from "unit-3"; close-match finds
        # the typo case ("histry-demo.txt"). Neither alone covers both.
        near = [name for name in sorted(remote_files)
                if wanted.lower() in name.lower()][:10]
        if not near:
            near = difflib.get_close_matches(wanted, sorted(remote_files), n=5, cutoff=0.6)
        message = f'"{wanted}" is not in the Drive folder ' \
                  f'"{folder_config["drive_folder_name"]}".'
        if near:
            message += "\n\nDid you mean:\n" + "\n".join(f"  {name}" for name in near)
        else:
            message += "\nRun `foldrive status` to see what Drive has."
        raise SystemExit(message)

    local_path = folder / wanted
    if local_path.exists() and not args.force:
        raise SystemExit(
            f"{local_path} already exists.\n"
            "Re-run with --force to overwrite it with Drive's copy."
        )

    local_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"restoring {wanted}")

    try:
        if remote_entry.get("is_google_native"):
            drive.download_native(
                service, remote_entry["id"], remote_entry["export_mime"], local_path
            )
            file_stat = local_path.stat()
            md5 = None
        else:
            drive.download(service, remote_entry["id"], local_path)
            file_stat = local_path.stat()
            md5 = remote_entry["md5"]
    except HttpError as api_error:
        raise SystemExit(f"Google Drive API error: {api_error.reason}")

    # Record it as synced, so the next run sees a settled file instead of deciding
    # it is a new local file to upload.
    current_state["files"][wanted] = {
        "size": file_stat.st_size,
        "mtime": file_stat.st_mtime,
        "md5": md5,
        "drive_file_id": remote_entry["id"],
        "drive_modified": remote_entry.get("modified"),
    }
    state.save_state(folder, current_state)
    history.record(folder, "restore", wanted, remote_entry["id"])

    print(f"Restored to {local_path}")
