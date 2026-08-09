from pathlib import PurePosixPath
from send2trash import send2trash
from . import drive, engine, prompts

def ensure_drive_folder(service, folder_relpath,root_folder_id, folder_ids):
    """Return the drive id for a relative folder path, creating level as needed"""
    if not folder_relpath:
        return root_folder_id
    if folder_relpath in folder_ids:
        return folder_ids[folder_relpath]

    path = PurePosixPath(folder_relpath)
    parent_relpath = str(path.parent) if str(path.parent)!="." else ""
    parent_id=ensure_drive_folder(service,parent_relpath,root_folder_id,folder_ids)

    new_id = drive.create_folder(service, path.name,parent_id)
    folder_ids[folder_relpath] = new_id
    return new_id


def push(service, folder, root_folder_id, current_state, actions, local_files, remote_files):
    summary={"uploaded":0, "updated":0, "trashed":0, "linked":0, "failed":0}
    folder_ids = current_state["folders"]

    for action in actions:
        relative_path = action.relpath
        try:
            if action.kind in ("upload_new", "upload_changed"):
                local_path = folder/relative_path
                existing = remote_files.get(relative_path)

                if action.kind == "upload_changed" and existing:
                    uploaded = drive.update(service,existing["id"],local_path)
                    summary["updated"] += 1
                else:
                    parent_relpath = str(PurePosixPath(relative_path).parent)
                    parent_relpath = "" if parent_relpath == "." else parent_relpath
                    parent_id = ensure_drive_folder(
                        service, parent_relpath,root_folder_id,folder_ids
                    )
                    uploaded  = drive.upload(
                        service, local_path, parent_id, PurePosixPath(relative_path).name
                    )
                    summary["uploaded"]+=1

                local_entry = local_files[relative_path]

                current_state["files"][relative_path]={
                    "size": local_entry["size"],
                    "mtime": local_entry["mtime"],
                    "md5": local_entry["md5"],
                    "drive_file_id": uploaded["id"],
                    "drive_modified": uploaded.get("modifiedTime"),
                }
            elif action.kind == "trash_remote":
                remote_entry = remote_files.get(relative_path)
                if remote_entry:
                    drive.trash(service, remote_entry["id"])
                current_state["files"].pop(relative_path, None)
                summary["trashed"]+=1

            elif action.kind== "link":
                local_entry=local_files[relative_path]
                remote_entry= remote_files[relative_path]
                current_state["files"][relative_path] = {
                    "size": local_entry["size"],
                    "mtime": local_entry["mtime"],
                    "md5": local_entry["md5"],
                    "drive_file_id": remote_entry["id"],
                    "drive_modified": remote_entry.get("modified"),
                }
                summary["linked"] += 1

            elif action.kind == "forget":
                current_state["files"].pop(relative_path, None)

        except Exception as failure:
            # One bad file (locked, vanished, API hiccup) must not stop the rest.
            summary["failed"] += 1
            print(f"  failed: {relative_path} ({failure})")
            
    return summary


def pull(service, folder, current_state,actions, local_files,remote_files):
    summary = {"downloaded": 0, "updated": 0, "recycled": 0, "linked": 0, "failed": 0}

    for action in actions:
        relative_path = action.relpath
        try:
            if action.kind in ("download_new","download_changed"):
                local_path = folder / relative_path
                local_path.parent.mkdir(parents=True,exist_ok=True)
                remote_entry = remote_files[relative_path]
                drive.download(service,remote_entry["id"],local_path)

                file_stat = local_path.stat()
                current_state["files"][relative_path]={
                    "size": file_stat.st_size,
                    "mtime": file_stat.st_mtime,
                    "md5": remote_entry["md5"],
                    "drive_file_id": remote_entry["id"],
                    "drive_modified": remote_entry.get("modified"),
                }
                if action.kind == "download_new":
                    summary["downloaded"] += 1
                else:
                    summary["updated"] += 1

            elif action.kind == "recycle_local":
                local_path = folder/relative_path
                if local_path.exists():
                    send2trash(str(local_path))
                current_state["files"].pop(relative_path,None)
                summary["recycled"]+=1

            elif action.kind == "link":
                local_entry = local_files[relative_path]
                remote_entry = remote_files[relative_path]
                current_state["files"][relative_path] = {
                    "size": local_entry["size"],
                    "mtime": local_entry["mtime"],
                    "md5": local_entry["md5"],
                    "drive_file_id": remote_entry["id"],
                    "drive_modified": remote_entry.get("modified"),
                }
                summary["linked"] +=1

            elif action.kind == "forget":
                current_state["files"].pop(relative_path, None)

        except Exception as failure:
            summary["failed"] += 1
            print(f"  failed: {relative_path} ({failure})")

    return summary


def _record(current_state, relative_path, size, mtime, md5, drive_file_id, drive_modified):
    """Write one file's snapshot entry — the single place that shape is defined.

    Holds both fingerprints (local size/mtime/md5 + Drive id/modifiedTime) since
    the next run diffs each side against them. Call it right after each success,
    so an interrupted run resumes from the last completed file.
    """
    current_state["files"][relative_path] = {
        "size": size, "mtime": mtime, "md5": md5,
        "drive_file_id": drive_file_id, "drive_modified": drive_modified,
    }


def _upload_local_file(service, folder, root_folder_id, folder_ids, relative_path):
    """Upload a local file that has no counterpart in Drive yet."""
    parent_relpath = str(PurePosixPath(relative_path).parent)
    parent_relpath = "" if parent_relpath == "." else parent_relpath
    parent_id = ensure_drive_folder(service, parent_relpath, root_folder_id, folder_ids)
    return drive.upload(
        service, folder / relative_path, parent_id, PurePosixPath(relative_path).name
    )


def resolve_conflict(service, folder, root_folder_id, current_state, action,
                     local_files, remote_files, choice):
    """choice: 'keep_both' | 'local' | 'drive' | 'skip'. Returns a note for the summary."""
    relative_path = action.relpath
    local_path = folder / relative_path
    local_entry = local_files[relative_path]
    remote_entry = remote_files[relative_path]
    folder_ids = current_state["folders"]

    if choice == "skip":
        return f"skipped {relative_path}"

    if choice == "local":
        uploaded = drive.update(service, remote_entry["id"], local_path)
        _record(current_state, relative_path, local_entry["size"], local_entry["mtime"],
                local_entry["md5"], uploaded["id"], uploaded.get("modifiedTime"))
        return f"local kept for {relative_path}"

    if choice == "drive":
        drive.download(service, remote_entry["id"], local_path)
        file_stat = local_path.stat()
        _record(current_state, relative_path, file_stat.st_size, file_stat.st_mtime,
                remote_entry["md5"], remote_entry["id"], remote_entry.get("modified"))
        return f"Drive kept for {relative_path}"

    # keep_both
    taken_names = set(local_files) | set(remote_files)

    if action.winner == "local":
        # Drive's version is preserved under a new name; local keeps the real one.
        drive_copy = engine.conflict_copy_name(relative_path, "drive", taken_names)
        drive.download(service, remote_entry["id"], folder / drive_copy)
        copy_uploaded = _upload_local_file(service, folder, root_folder_id, folder_ids, drive_copy)
        copy_stat = (folder / drive_copy).stat()
        _record(current_state, drive_copy, copy_stat.st_size, copy_stat.st_mtime,
                remote_entry["md5"], copy_uploaded["id"], copy_uploaded.get("modifiedTime"))

        winner_uploaded = drive.update(service, remote_entry["id"], local_path)
        _record(current_state, relative_path, local_entry["size"], local_entry["mtime"],
                local_entry["md5"], winner_uploaded["id"], winner_uploaded.get("modifiedTime"))
        return f"kept both: {relative_path} (local) + {drive_copy}"

    if action.winner == "drive":
        # Local version is renamed aside; Drive's version takes the real name.
        local_copy = engine.conflict_copy_name(relative_path, "local", taken_names)
        (folder / relative_path).rename(folder / local_copy)
        copy_uploaded = _upload_local_file(service, folder, root_folder_id, folder_ids, local_copy)
        _record(current_state, local_copy, local_entry["size"], local_entry["mtime"],
                local_entry["md5"], copy_uploaded["id"], copy_uploaded.get("modifiedTime"))

        drive.download(service, remote_entry["id"], local_path)
        file_stat = local_path.stat()
        _record(current_state, relative_path, file_stat.st_size, file_stat.st_mtime,
                remote_entry["md5"], remote_entry["id"], remote_entry.get("modified"))
        return f"kept both: {relative_path} (Drive) + {local_copy}"

    # tie: nobody keeps the original name
    local_copy = engine.conflict_copy_name(relative_path, "local", taken_names)
    drive_copy = engine.conflict_copy_name(relative_path, "drive", taken_names | {local_copy})

    (folder / relative_path).rename(folder / local_copy)
    local_uploaded = _upload_local_file(service, folder, root_folder_id, folder_ids, local_copy)
    _record(current_state, local_copy, local_entry["size"], local_entry["mtime"],
            local_entry["md5"], local_uploaded["id"], local_uploaded.get("modifiedTime"))

    drive.rename(service, remote_entry["id"], PurePosixPath(drive_copy).name)
    drive.download(service, remote_entry["id"], folder / drive_copy)
    copy_stat = (folder / drive_copy).stat()
    _record(current_state, drive_copy, copy_stat.st_size, copy_stat.st_mtime,
            remote_entry["md5"], remote_entry["id"], remote_entry.get("modified"))
    current_state["files"].pop(relative_path, None)
    return f"tie: kept {local_copy} + {drive_copy}"

def resolve_all_conflicts(service, folder, root_folder_id, current_state, conflicts,
                          local_files, remote_files, interactive, default_choice="keep_both"):
    notes = []
    forced_choice = None
    for action in conflicts:
        try:
            if forced_choice:
                choice = forced_choice
            elif interactive:
                choice, apply_to_all = prompts.ask_conflict(
                    action, local_files[action.relpath], remote_files[action.relpath]
                )
                if apply_to_all:
                    forced_choice = choice
            else:
                choice = default_choice
            notes.append(resolve_conflict(service, folder, root_folder_id, current_state,
                                          action, local_files, remote_files, choice))
        except Exception as failure:
            notes.append(f"failed {action.relpath} ({failure})")
    return notes
