from pathlib import Path

from googleapiclient.errors import HttpError

from .. import auth, config, drive, engine, scanner, state

KIND_LABELS = {
    "upload_new": "new locally      -> upload",
    "upload_changed": "changed locally  -> upload",
    "download_new": "new in Drive     -> download",
    "download_changed": "changed in Drive -> download",
    "trash_remote": "deleted locally  -> trash in Drive",
    "recycle_local": "deleted in Drive -> Recycle Bin",
    "conflict": "CONFLICT         -> both sides changed",
    "link": "identical        -> just remember it",
    "forget": "gone from both   -> forget",
    "download_new_doc": "new in Drive (Doc)    -> download as .docx",
    "download_changed_doc": "changed in Drive (Doc) -> download again",
    "download_changed_doc_keep_local": "changed both sides    -> download, local kept as a copy",
    "upload_changed_doc": "changed locally       -> upload back into the Doc",
    "upload_changed_doc_keep_drive": "changed both sides    -> upload, Drive kept as a copy",
    "conflict_doc": "CONFLICT (Doc)        -> both sides changed",
}


def run(args):
    folder = config.find_config_root(Path.cwd())
    if folder is None:
        raise SystemExit("Not a foldrive folder. Run: foldrive init")

    folder_config = config.load_config(folder)
    current_state = state.load_state(folder)
    service = auth.get_service()

    try:
        local_files = scanner.scan(folder, folder_config["ignore"], current_state["files"])
        remote_files, _remote_folders, skipped_google_native = drive.list_tree(
            service, folder_config["drive_folder_id"]
        )
    except HttpError as api_error:
        raise SystemExit(f"Google Drive API error: {api_error.reason}")
    except OSError:
        raise SystemExit("Network error — are you connected to the internet?")

    is_first_sync = not current_state["files"]

    actions = engine.classify(local_files, remote_files, current_state["files"])
    actions, native_notes = engine.apply_google_native_mode(
        actions, remote_files, folder_config["google_native"]
    )
    actions, delete_notes = engine.apply_delete_policy(
        actions, folder_config["delete_policy"]
    )
    if is_first_sync:
        actions = engine.downgrade_for_first_sync(actions)

    print(f"Folder : {folder}")
    print(f"Drive  : {folder_config['drive_folder_name']}")
    print(f"Local  : {len(local_files)} files    Drive: {len(remote_files)} files")
    if is_first_sync:
        print("This folder has never been synced — the first sync merges both sides.")
    print()

    if not actions:
        print("Everything is in sync.")
    else:
        counts_by_kind = {}
        for action in actions:
            counts_by_kind[action.kind] = counts_by_kind.get(action.kind, 0) + 1
        for kind, count in sorted(counts_by_kind.items()):
            print(f"  {KIND_LABELS.get(kind, kind)}   {count} file(s)")
        print()

        shown_limit = 40 if not args.all else len(actions)
        for action in actions[:shown_limit]:
            label = KIND_LABELS.get(action.kind, action.kind)
            if action.kind == "conflict":
                if action.winner:
                    label = f"CONFLICT         -> {action.winner} is newer, keeps the name"
                else:
                    label = "CONFLICT         -> same age, keeping both copies"
            print(f"  {label}   {action.relpath}")
        if len(actions) > shown_limit:
            print(f"  ... and {len(actions) - shown_limit} more (use --all to list every file)")

        print()
        print(f"{len(actions)} change(s) pending. Run `foldrive sync` to apply.")

    for note in native_notes + delete_notes:
        print(f"\n({note})")

    if skipped_google_native:
        print(f"\n({skipped_google_native} Google Forms/Drawings/Sites skipped - they have no downloadable form.)")
