import argparse
from googleapiclient.errors import HttpError
from . import __version__, auth, drive, config
from pathlib import Path 


def cmd_push(args):
    print("push: not implemented yet")


def cmd_pull(args):
    print("pull: not implemented yet")


def cmd_sync(args):
    print("sync: not implemented yet")


def cmd_init(args):
    



def cmd_status(args):
    print("status: not implemented yet")



def cmd_login(args):
    already = auth.get_credentials() is not None
    auth.login()
    if already:
        print("Already logged in.")
    else:
        print(f"Logged in. Token saved to {auth.TOKEN_PATH}")


def cmd_whoami(args):
    service = auth.get_service()
    info = service.about().get(fields="user").execute()
    print(f"Logged in as {info['user']['emailAddress']}")


def cmd_logout(args):
    if auth.logout():
        print("Logged out.")
    else:
        print("Not logged in.")


def cmd_tick(args):
    print("tick: not implemented yet")

def cmd_ls(args):
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


def cmd_autostart(args):
    print("autostart: not implemented yet")


def main():
    parser = argparse.ArgumentParser(
        prog="foldrive",
        description="Pair a local folder with a Google Drive folder.",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"foldrive {__version__}",
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    p = sub.add_parser(
        "login",
        help="Sign in with your Google account",
    )
    p.set_defaults(func=cmd_login)

    p = sub.add_parser(
        "whoami",
        help="Show the currently signed-in Google account",
    )
    p.set_defaults(func=cmd_whoami)

    p = sub.add_parser(
        "ls",
        help="List the contents of a Drive folder by name",
    )
    p.add_argument(
        "name",
        nargs="?",
        default=None,
        help="Drive folder name to look up (you'll be asked if omitted)",
    )
    p.set_defaults(func=cmd_ls)


    p = sub.add_parser(
        "init",
        help="Initialize the current folder for foldrive syncing",
    )
    p.set_defaults(func=cmd_init)

    p = sub.add_parser(
        "status",
        help="Show local and remote sync status",
    )
    p.set_defaults(func=cmd_status)

    p = sub.add_parser(
        "push",
        help="Upload local changes to Google Drive",
    )
    p.set_defaults(func=cmd_push)

    p = sub.add_parser(
        "pull",
        help="Download remote changes from Google Drive",
    )
    p.set_defaults(func=cmd_pull)

    p = sub.add_parser(
        "sync",
        help="Synchronize local and Google Drive changes",
    )
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser(
        "tick",
        help="run any scheduled syncs that are due (used by the background task)",
    )
    p.set_defaults(func=cmd_tick)

    p = sub.add_parser(
        "autostart",
        help="Enable foldrive to start automatically when you log in",
    )
    p.set_defaults(func=cmd_autostart)

    p = sub.add_parser("logout",help="Sign out and forget the saved Google token",
    )
    p.set_defaults(func=cmd_logout)


    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()