"""foldrive CLI: argument parsing and dispatch. Command logic lives in commands/."""

import argparse

from . import __version__
from .commands import (
    autostart, init, log, login, logout, ls, pull, push, restore, setup, status,
    sync, tick, whoami,
)


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
        "setup",
        help="One-time Google setup: install your OAuth client file",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to the client JSON downloaded from Google Cloud "
             "(omit to print the setup steps)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Replace an already-installed client file",
    )
    p.set_defaults(func=setup.run)

    p = sub.add_parser(
        "login",
        help="Sign in with your Google account",
    )
    p.set_defaults(func=login.run)

    p = sub.add_parser(
        "whoami",
        help="Show the currently signed-in Google account",
    )
    p.set_defaults(func=whoami.run)

    p = sub.add_parser(
        "logout",
        help="Sign out and forget the saved Google token",
    )
    p.set_defaults(func=logout.run)

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
    p.set_defaults(func=ls.run)

    p = sub.add_parser(
        "init",
        help="Initialize the current folder for foldrive syncing",
    )
    p.set_defaults(func=init.run)

    p = sub.add_parser(
        "status",
        help="Show local and remote sync status",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="List every pending file instead of the first 40",
    )
    p.set_defaults(func=status.run)

    p = sub.add_parser(
        "push",
        help="Upload local changes to Google Drive",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip the first-sync confirmation prompt",
    )
    p.add_argument(
        "--allow-mass-delete",
        action="store_true",
        help="Permit a run that would delete most of the folder",
    )
    p.set_defaults(func=push.run)

    p = sub.add_parser(
        "pull",
        help="Download remote changes from Google Drive",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Never prompt; use safe defaults",
    )
    p.add_argument(
        "--allow-mass-delete",
        action="store_true",
        help="Permit a run that would delete most of the folder",
    )
    p.set_defaults(func=pull.run)

    p = sub.add_parser(
        "sync",
        help="Synchronize local and Google Drive changes",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Never prompt; use safe defaults",
    )
    p.add_argument(
        "--allow-mass-delete",
        action="store_true",
        help="Permit a run that would delete most of the folder",
    )
    p.set_defaults(func=sync.run)

    p = sub.add_parser(
        "log",
        help="Show what foldrive has done to this folder",
    )
    p.add_argument(
        "-n", "--number",
        type=int,
        default=20,
        help="How many entries to show (default 20)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="Show the entire history",
    )
    p.set_defaults(func=log.run)

    p = sub.add_parser(
        "restore",
        help="Bring one file back from Drive",
    )
    p.add_argument(
        "path",
        help="Path of the file inside this folder, e.g. notes/unit-3.pdf",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the local file if it already exists",
    )
    p.set_defaults(func=restore.run)

    p = sub.add_parser(
        "tick",
        help="Run any scheduled syncs that are due (used by the background task)",
    )
    p.set_defaults(func=tick.run)

    p = sub.add_parser(
        "autostart",
        help="Enable foldrive to start automatically when you log in",
    )
    p.add_argument("--remove", action="store_true",help="Disable background sync")
    p.add_argument("--status",action="store_true",help="Show whether it's registered")
    p.set_defaults(func=autostart.run)

    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        # Ctrl-C is a normal way to stop a long sync, not a crash. Each command
        # saves its snapshot in a `finally`, so whatever finished is already
        # recorded and the next run picks up from there.
        raise SystemExit("\nInterrupted. Finished files are saved - re-run to continue.")


if __name__ == "__main__":
    main()
