"""Fabricate a real conflict for testing: same file, different content on both sides.

Usage (from inside a synced folder):
    python tools/make_conflict.py shared.txt
"""

import sys
import tempfile
from pathlib import Path

from foldrive import auth, config, drive, scanner, state


def main():
    file_name = sys.argv[1] if len(sys.argv) > 1 else "shared.txt"
    folder = config.find_config_root(Path.cwd())
    if folder is None:
        raise SystemExit("Not a foldrive folder.")

    folder_config = config.load_config(folder)
    current_state = state.load_state(folder)
    service = auth.get_service()
    local_path = folder / file_name

    remote_files, _folders, _skipped = drive.list_tree(service, folder_config["drive_folder_id"])
    if file_name not in remote_files:
        raise SystemExit(f"'{file_name}' is not in Drive yet — run `foldrive push` first.")

    # Change Drive's copy by uploading different bytes to the same file id.
    drive_version = Path(tempfile.gettempdir()) / f"conflict-{file_name}"
    drive_version.write_text("DRIVE SIDE VERSION\n", encoding="utf-8")
    drive.update(service, remote_files[file_name]["id"], drive_version)

    # Change the local copy differently.
    local_path.write_text("LOCAL SIDE VERSION\n", encoding="utf-8")

    print(f"Conflict created on '{file_name}':")
    print("  local  -> LOCAL SIDE VERSION")
    print("  Drive  -> DRIVE SIDE VERSION")
    print("\nNow run: foldrive pull")


if __name__ == "__main__":
    main()
