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
            print(f"  {label}   {action.relpath}")
        if len(actions) > shown_limit:
            print(f"  ... and {len(actions) - shown_limit} more (use --all to list every file)")

        print()
        print(f"{len(actions)} change(s) pending. Run `foldrive sync` to apply.")

    if skipped_google_native:
        print(f"\n({skipped_google_native} Google Docs/Sheets/Slides skipped — they have no downloadable content.)")
