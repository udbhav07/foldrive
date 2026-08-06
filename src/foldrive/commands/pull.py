import sys
from pathlib import Path

from googleapiclient.errors import HttpError

from .. import auth, config, drive, engine, scanner, state, executor


def run(args):
    folder = config.find_config_root(Path.cwd())
    if folder is None:
        raise SystemExit("Not a foldrive folder. Run: foldrive init")

    folder_config = config.load_config(folder)
    current_state = state.load_state(folder)
    service = auth.get_service()

    try:
        local_files = scanner.scan(folder, folder_config["ignore"], current_state["files"])
        remote_files, remote_folders, _skipped = drive.list_tree(
            service, folder_config["drive_folder_id"]
        )
    except HttpError as api_error:
        raise SystemExit(f"Google Drive API error: {api_error.reason}")
    except OSError:
        raise SystemExit("Network error — are you connected to the internet?")

    current_state["folders"].update(remote_folders)

    is_first_sync = not current_state["files"]
    actions = engine.classify(local_files, remote_files, current_state["files"])
    if is_first_sync:
        actions = engine.downgrade_for_first_sync(actions)

    pull_actions = [a for a in actions if a.kind in engine.DOWNLOAD_KINDS or a.kind in ("link", "forget")]
    conflicts = [a for a in actions if a.kind == "conflict"]

    if not pull_actions:
        print("Nothing to pull.")
        if conflicts:
            print(f"({len(conflicts)} conflict(s) need `foldrive sync`.)")
        return

    transfers = [a for a in pull_actions if a.kind not in ("link", "forget")]
    print(f"{len(transfers)} file(s) to fetch, {len(pull_actions) - len(transfers)} to link.")

    if is_first_sync and transfers and sys.stdin.isatty() and not args.yes:
        for action in transfers[:20]:
            print(f"  {action.kind}   {action.relpath}")
        if len(transfers) > 20:
            print(f"  ... and {len(transfers) - 20} more")
        if input("First sync for this folder. Proceed? [y/N] ").strip().lower() != "y":
            raise SystemExit("Cancelled. Nothing was downloaded.")

    try:
        summary = executor.pull(
            service, folder, current_state, pull_actions, local_files, remote_files,
        )

    finally:
        # Saved even on Ctrl-C: whatever succeeded stays remembered.
        state.save_state(folder, current_state)

    print(
        f"downloaded {summary['downloaded']}, updated {summary['updated']}, "
        f"recycled {summary['recycled']}, linked {summary['linked']}, failed {summary['failed']}"
    )
    if conflicts:
        print(f"{len(conflicts)} conflict(s) skipped — resolve with `foldrive sync`.")
