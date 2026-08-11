import sys
from pathlib import Path
from datetime import datetime, timezone

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
    actions, _native_notes = engine.apply_google_native_mode(
        actions, remote_files, folder_config["google_native"]
    )
    if is_first_sync:
        actions = engine.downgrade_for_first_sync(actions)

    pull_actions = [a for a in actions if a.kind in engine.DOWNLOAD_KINDS or a.kind in ("link", "forget")]
    conflicts = [a for a in actions if a.kind in ("conflict", "conflict_doc")]

    if not pull_actions and not conflicts:
        # Nothing to do still counts as a successful check — otherwise the folder
        # stays "overdue" forever and every tick rescans it for nothing.
        current_state["last_pull_ok"] = datetime.now(timezone.utc).isoformat()
        state.save_state(folder, current_state)
        print("Nothing to pull.")
        return

    transfers = [a for a in pull_actions if a.kind not in ("link", "forget")]
    if pull_actions:
        print(f"{len(transfers)} file(s) to fetch, {len(pull_actions) - len(transfers)} to link.")
    if conflicts:
        print(f"{len(conflicts)} conflict(s) to resolve.")

    if is_first_sync and transfers and sys.stdin.isatty() and not args.yes:
        for action in transfers[:20]:
            print(f"  {action.kind}   {action.relpath}")
        if len(transfers) > 20:
            print(f"  ... and {len(transfers) - 20} more")
        if input("First sync for this folder. Proceed? [y/N] ").strip().lower() != "y":
            raise SystemExit("Cancelled. Nothing was downloaded.")

    # Every question is asked before the first transfer, so the run needs no babysitting.
    conflict_choices = []
    if conflicts:
        conflict_choices = executor.collect_conflict_choices(
            conflicts, local_files, remote_files,
            interactive=prompts.should_prompt(args, folder_config),
            overrides=folder_config.get("conflict_overrides", {}),
        )

    conflict_notes = []
    try:
        summary = executor.pull(
            service, folder, current_state, pull_actions, local_files, remote_files,
        )
        if conflict_choices:
            conflict_notes = executor.apply_conflict_choices(
                service, folder, folder_config["drive_folder_id"], current_state,
                conflict_choices, local_files, remote_files,
            )
        current_state["last_pull_ok"] = datetime.now(timezone.utc).isoformat()
    finally:
        # Saved even on Ctrl-C: whatever succeeded stays remembered.
        state.save_state(folder, current_state)

    print(
        f"downloaded {summary['downloaded']}, updated {summary['updated']}, "
        f"recycled {summary['recycled']}, linked {summary['linked']}, failed {summary['failed']}"
    )
    for note in conflict_notes:
        print(f"  {note}")
