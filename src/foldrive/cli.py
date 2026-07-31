"""foldrive CLI: argument parsing and dispatch. Command logic lives in commands/."""

import argparse

from . import __version__
from .commands import autostart, init, login, logout, ls, pull, push, status, sync, tick, whoami


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
    p.set_defaults(func=status.run)

    p = sub.add_parser(
        "push",
        help="Upload local changes to Google Drive",
    )
    p.set_defaults(func=push.run)

    p = sub.add_parser(
        "pull",
        help="Download remote changes from Google Drive",
    )
    p.set_defaults(func=pull.run)

    p = sub.add_parser(
        "sync",
        help="Synchronize local and Google Drive changes",
    )
    p.set_defaults(func=sync.run)

    p = sub.add_parser(
        "tick",
        help="Run any scheduled syncs that are due (used by the background task)",
    )
    p.set_defaults(func=tick.run)

    p = sub.add_parser(
        "autostart",
        help="Enable foldrive to start automatically when you log in",
    )
    p.set_defaults(func=autostart.run)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
