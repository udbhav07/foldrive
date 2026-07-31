from googleapiclient.errors import HttpError

from .. import auth, drive


def run(args):
    if args.name is None:
        args.name = input("Enter the Drive folder name: ").strip()
        if not args.name:
            raise SystemExit("No folder name given.")

    service = auth.get_service()
    try:
        matching_folders = drive.find_folder_by_name(service, args.name)
        if not matching_folders:
            print(f"No Drive folder named '{args.name}' found.")
            return
        if len(matching_folders) > 1:
            print(f"Multiple folders named '{args.name}' found.")
            for folder_match in matching_folders:
                print(f" {folder_match['name']} (id: {folder_match['id']})")
            return

        children = drive.list_children(service, matching_folders[0]["id"])
        if not children:
            print("(empty folder)")
            return
        folders_first_alphabetical = sorted(
            children,
            key=lambda child: (child["mimeType"] != drive.FOLDER_MIME_TYPE, child["name"].lower()),
        )
        print(f"Found one folder with the name '{args.name}', following are the contents in Google Drive of that folder: ")
        for child in folders_first_alphabetical:
            if child["mimeType"] == drive.FOLDER_MIME_TYPE:
                print(f"  {child['name']}/")
            else:
                size_kb = int(child.get("size", 0)) // 1024
                print(f"  {child['name']}  ({size_kb} KB)")
    except HttpError as api_error:
        raise SystemExit(f"Google Drive API error: {api_error.reason}")
    except OSError:
        raise SystemExit("Network error — are you connected to the internet?")
