import copy
from pathlib import Path

from googleapiclient.errors import HttpError

from .. import auth, config, drive


def run(args):
    folder = Path.cwd()

    if (folder / config.CONFIG_NAME).exists():
        raise SystemExit("Already initialized. Edit .googledrive.json to change settings.")

    enclosing_root = config.find_config_root(folder.parent)
    if enclosing_root is not None:
        raise SystemExit(f"This folder is inside '{enclosing_root}', which is already synced.")

    service = auth.get_service()
    try:
        matching_folders = drive.find_folder_by_name(service, folder.name)

        if len(matching_folders) > 1:
            print(f"Multiple Drive folders are named '{folder.name}':")
            for folder_match in matching_folders:
                print(f"  {folder_match['name']}  (id: {folder_match['id']})")
            raise SystemExit(
                "foldrive can't tell them apart yet. Rename the extras in Drive, then re-run init."
            )

        elif len(matching_folders) == 1:
            drive_folder_id = matching_folders[0]["id"]
            answer = input(f"Found Drive folder '{folder.name}'. Link this local folder to it? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit("Cancelled. Nothing was created or linked.")

        else:
            answer = input(f"No Drive folder named '{folder.name}' found. Create it in My Drive? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit("Cancelled. Nothing was created or linked.")
            drive_folder_id = drive.create_folder(service, folder.name)
            print(f"Created Drive folder '{folder.name}'.")

        new_config = copy.deepcopy(config.DEFAULT_CONFIG)
        new_config["drive_folder_id"] = drive_folder_id
        new_config["drive_folder_name"] = folder.name
        config.save_config(folder, new_config)
        config.register_folder(folder)

        print(f"Linked '{folder}'  <->  Drive folder '{folder.name}'.")
        print("Settings saved in .googledrive.json — edit schedules/ignores there.")
        print("Next: run `foldrive status` to see what a first sync would do.")

    except HttpError as api_error:
        raise SystemExit(f"Google Drive API error: {api_error.reason}")
    except OSError:
        raise SystemExit("Network error — are you connected to the internet?")
