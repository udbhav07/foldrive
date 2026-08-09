import sys
from pathlib import Path

from googleapiclient.errors import HttpError

from .. import auth, config, drive, engine, scanner, state, executor, prompts


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

    push_actions = [a for a in actions if a.kind in engine.UPLOAD_KINDS or a.kind in ("link", "forget")]
    conflicts = [a for a in actions if a.kind == "conflict"]

    if not push_actions:
        print("Nothing to push.")
        if conflicts:
            print(f"({len(conflicts)} conflict(s) need `foldrive sync` — coming in step 8.)")
        return

    transfers = [a for a in push_actions if a.kind not in ("link", "forget")]
    print(f"{len(transfers)} file(s) to send, {len(push_actions) - len(transfers)} to link.")

    if is_first_sync and transfers and sys.stdin.isatty() and not args.yes:
        for action in transfers[:20]:
            print(f"  {action.kind}   {action.relpath}")
        if len(transfers) > 20:
            print(f"  ... and {len(transfers) - 20} more")
        if input("First sync for this folder. Proceed? [y/N] ").strip().lower() != "y":
            raise SystemExit("Cancelled. Nothing was uploaded.")

    conflict_notes = []
    try:
        summary = executor.push(
            service, folder, folder_config["drive_folder_id"],
            current_state, push_actions, local_files, remote_files,
        )
        if conflicts:
            conflict_notes = executor.resolve_all_conflicts(
                service, folder, folder_config["drive_folder_id"], current_state,
                conflicts, local_files, remote_files,
                interactive=prompts.should_prompt(args, folder_config),
            )
    finally:
        # Saved even on Ctrl-C: whatever succeeded stays remembered.
        state.save_state(folder, current_state)

    print(
        f"uploaded {summary['uploaded']}, updated {summary['updated']}, "
        f"trashed {summary['trashed']}, linked {summary['linked']}, failed {summary['failed']}"
    )
    for note in conflict_notes:
        print(f"  {note}")

