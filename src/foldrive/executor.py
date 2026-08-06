from pathlib import PurePosixPath
from send2trash import send2trash
from . import drive

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