from pathlib import PurePosixPath
from send2trash import send2trash
from . import drive, engine, history, progress, prompts, state

# How many transfers between snapshot writes. Low enough that a hard kill costs
# little re-work, high enough that the write itself stays negligible.
SAVE_EVERY = 25


def _periodic_save(folder, current_state, completed_transfers):
    """Persist mid-run so a killed process doesn't lose everything it just did.

    Safe at any point: each file's entry is recorded the moment its own transfer
    succeeds, so the snapshot always describes exactly the work that is finished.
    save_state writes a temp file and os.replace()s it, so a crash during the save
    leaves either the old snapshot or the new one - never a half-written one.
    """
    if completed_transfers and completed_transfers % SAVE_EVERY == 0:
        state.save_state(folder, current_state)


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
    reporter = progress.Reporter.for_actions(actions)
    history.trim_if_large(folder)

    for action in actions:
        relative_path = action.relpath
        reporter.starting(action)
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
            elif action.kind in ("upload_changed_doc", "upload_changed_doc_keep_drive"):
                local_path = folder / relative_path
                remote_entry = remote_files[relative_path]

                if action.kind == "upload_changed_doc_keep_drive":
                    kept_name = engine.conflict_copy_name(
                        relative_path, "drive", set(local_files) | set(remote_files)
                    )
                    reporter.detail(f"keeping Drive's version as {kept_name}")
                    drive.download_native(
                        service, remote_entry["id"], remote_entry["export_mime"],
                        folder / kept_name,
                    )

                uploaded = drive.upload_doc(
                    service, remote_entry["id"], local_path, remote_entry["native_mime"]
                )
                local_entry = local_files[relative_path]
                _record(current_state, relative_path, local_entry["size"], local_entry["mtime"],
                        None, uploaded["id"], uploaded.get("modifiedTime"))
                summary["updated"] += 1

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

            # Recorded only after the action succeeded, so history never claims
            # work that did not happen.
            if action.kind != "forget":
                history.record(
                    folder, action.kind, relative_path,
                    current_state["files"].get(relative_path, {}).get("drive_file_id")
                    or (remote_files.get(relative_path) or {}).get("id"),
                )
            _periodic_save(folder, current_state, reporter.completed)

        except Exception as failure:
            # One bad file (locked, vanished, API hiccup) must not stop the rest.
            summary["failed"] += 1
            print(f"  failed: {relative_path} ({failure})")
            
    return summary


def pull(service, folder, current_state,actions, local_files,remote_files):
    summary = {"downloaded": 0, "updated": 0, "recycled": 0, "linked": 0, "failed": 0}
    reporter = progress.Reporter.for_actions(actions)
    history.trim_if_large(folder)

    for action in actions:
        relative_path = action.relpath
        reporter.starting(action)
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

            elif action.kind in ("download_new_doc", "download_changed_doc",
                                 "download_changed_doc_keep_local"):
                local_path = folder / relative_path
                local_path.parent.mkdir(parents=True, exist_ok=True)
                remote_entry = remote_files[relative_path]

                if action.kind == "download_changed_doc_keep_local" and local_path.exists():
                    # Nothing is ever silently destroyed: the local edit is renamed
                    # aside before the fresh download lands on top of it.
                    kept_name = engine.conflict_copy_name(
                        relative_path, "local", set(local_files) | set(remote_files)
                    )
                    reporter.detail(f"keeping the local edit as {kept_name}")
                    local_path.rename(folder / kept_name)

                drive.download_native(
                    service, remote_entry["id"], remote_entry["export_mime"], local_path
                )
                file_stat = local_path.stat()
                # md5 stays None: the snapshot compares Docs by drive_modified only.
                _record(current_state, relative_path, file_stat.st_size, file_stat.st_mtime,
                        None, remote_entry["id"], remote_entry.get("modified"))
                summary["downloaded"] += 1

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

            # Recorded only after the action succeeded, so history never claims
            # work that did not happen.
            if action.kind != "forget":
                history.record(
                    folder, action.kind, relative_path,
                    current_state["files"].get(relative_path, {}).get("drive_file_id")
                    or (remote_files.get(relative_path) or {}).get("id"),
                )
            _periodic_save(folder, current_state, reporter.completed)

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
                     local_files, remote_files, choice, reporter=progress.SILENT):
    """choice: 'keep_both' | 'local' | 'drive' | 'skip'. Returns a note for the summary.

    One conflict can be three transfers, so each step reports itself - otherwise a
    single line sits on screen for a minute with nothing to say what it's doing.
    """
    relative_path = action.relpath
    local_path = folder / relative_path
    local_entry = local_files[relative_path]
    remote_entry = remote_files[relative_path]
    folder_ids = current_state["folders"]

    if choice == "skip":
        return f"skipped {relative_path}"

    if choice == "local":
        reporter.detail("uploading the local version over Drive's")
        uploaded = drive.update(service, remote_entry["id"], local_path)
        _record(current_state, relative_path, local_entry["size"], local_entry["mtime"],
                local_entry["md5"], uploaded["id"], uploaded.get("modifiedTime"))
        return f"local kept for {relative_path}"

    if choice == "drive":
        reporter.detail("downloading Drive's version over the local one")
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
        reporter.detail(f"downloading Drive's version as {drive_copy}")
        drive.download(service, remote_entry["id"], folder / drive_copy)
        reporter.detail(f"uploading {drive_copy}")
        copy_uploaded = _upload_local_file(service, folder, root_folder_id, folder_ids, drive_copy)
        copy_stat = (folder / drive_copy).stat()
        _record(current_state, drive_copy, copy_stat.st_size, copy_stat.st_mtime,
                remote_entry["md5"], copy_uploaded["id"], copy_uploaded.get("modifiedTime"))

        reporter.detail(f"uploading the local version as {relative_path}")
        winner_uploaded = drive.update(service, remote_entry["id"], local_path)
        _record(current_state, relative_path, local_entry["size"], local_entry["mtime"],
                local_entry["md5"], winner_uploaded["id"], winner_uploaded.get("modifiedTime"))
        return f"kept both: {relative_path} (local) + {drive_copy}"

    if action.winner == "drive":
        # Local version is renamed aside; Drive's version takes the real name.
        local_copy = engine.conflict_copy_name(relative_path, "local", taken_names)
        reporter.detail(f"renaming the local version aside as {local_copy}")
        (folder / relative_path).rename(folder / local_copy)
        reporter.detail(f"uploading {local_copy}")
        copy_uploaded = _upload_local_file(service, folder, root_folder_id, folder_ids, local_copy)
        _record(current_state, local_copy, local_entry["size"], local_entry["mtime"],
                local_entry["md5"], copy_uploaded["id"], copy_uploaded.get("modifiedTime"))

        reporter.detail(f"downloading Drive's version as {relative_path}")
        drive.download(service, remote_entry["id"], local_path)
        file_stat = local_path.stat()
        _record(current_state, relative_path, file_stat.st_size, file_stat.st_mtime,
                remote_entry["md5"], remote_entry["id"], remote_entry.get("modified"))
        return f"kept both: {relative_path} (Drive) + {local_copy}"

    # tie: nobody keeps the original name
    local_copy = engine.conflict_copy_name(relative_path, "local", taken_names)
    drive_copy = engine.conflict_copy_name(relative_path, "drive", taken_names | {local_copy})

    reporter.detail(f"renaming the local version aside as {local_copy}")
    (folder / relative_path).rename(folder / local_copy)
    reporter.detail(f"uploading {local_copy}")
    local_uploaded = _upload_local_file(service, folder, root_folder_id, folder_ids, local_copy)
    _record(current_state, local_copy, local_entry["size"], local_entry["mtime"],
            local_entry["md5"], local_uploaded["id"], local_uploaded.get("modifiedTime"))

    reporter.detail(f"renaming Drive's version to {drive_copy}")
    drive.rename(service, remote_entry["id"], PurePosixPath(drive_copy).name)
    reporter.detail(f"downloading {drive_copy}")
    drive.download(service, remote_entry["id"], folder / drive_copy)
    copy_stat = (folder / drive_copy).stat()
    _record(current_state, drive_copy, copy_stat.st_size, copy_stat.st_mtime,
            remote_entry["md5"], remote_entry["id"], remote_entry.get("modified"))
    current_state["files"].pop(relative_path, None)
    return f"tie: kept {local_copy} + {drive_copy}"

def resolve_all_conflicts(service, folder, root_folder_id, current_state, conflicts,
                          local_files, remote_files, interactive, default_choice="keep_both"):
    """Deprecated: use collect_conflict_choices() then apply_conflict_choices()."""
    choices = collect_conflict_choices(
        conflicts, local_files, remote_files, interactive, {}, default_choice
    )
    return apply_conflict_choices(service, folder, root_folder_id, current_state,
                                  choices, local_files, remote_files)


def collect_conflict_choices(conflicts, local_files, remote_files, interactive,
                             overrides=None, default_choice="keep_both"):
    """Decide every conflict up front, before any transfer starts.

    Asking first means the user answers in the first few seconds and the rest of
    the run needs nobody watching it. Pure decisions — no Drive or disk writes.
    """
    overrides = overrides or {}
    choices = []
    forced_choice = None

    for action in conflicts:
        override = overrides.get(action.relpath)
        if override:
            print(f"   {action.relpath}: '{override}' (from conflict_overrides)")
            choices.append((action, override))
            continue
        if forced_choice:
            choices.append((action, forced_choice))
            continue
        if interactive:
            choice, apply_to_all = prompts.ask_conflict(
                action, local_files[action.relpath], remote_files[action.relpath]
            )
            if apply_to_all:
                forced_choice = choice
        else:
            choice = default_choice
        choices.append((action, choice))

    return choices


def apply_conflict_choices(service, folder, root_folder_id, current_state, choices,
                           local_files, remote_files):
    """Execute decisions already made. Never prompts."""
    notes = []
    reporter = progress.Reporter.for_conflicts(choices)
    for action, choice in choices:
        if choice != "skip":
            reporter.item(progress.CONFLICT_LABELS.get(choice, choice), action.relpath)
        try:
            notes.append(resolve_conflict(service, folder, root_folder_id, current_state,
                                          action, local_files, remote_files, choice,
                                          reporter))
            # Saved after every conflict, not every SAVE_EVERY: one conflict is
            # three or four transfers, so the write costs nothing next to redoing it.
            state.save_state(folder, current_state)
        except Exception as failure:
            notes.append(f"failed {action.relpath} ({failure})")
    return notes
