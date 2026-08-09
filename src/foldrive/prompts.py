"""Interactive prompts. Kept apart so executors stay non-interactive."""

import sys
from datetime import datetime, timezone

from . import engine

# letter -> (choice, apply_to_all).  Uppercase = apply to every remaining conflict.
VALID_CHOICES = {
    "k": ("keep_both", False),
    "l": ("local", False),
    "d": ("drive", False),
    "s": ("skip", False),
    "K": ("keep_both", True),
    "L": ("local", True),
    "D": ("drive", True),
    "S": ("skip", True),
}

def should_prompt(args, folder_config):
    if getattr(args, "yes", False):
        return False
    if folder_config.get("conflict_policy") == "keep_both":
        return False
    return sys.stdin.isatty()


def _readable(epoch_seconds):
    if epoch_seconds is None:
        return "unknown"
    return datetime.fromtimestamp(epoch_seconds, timezone.utc).strftime("%Y-%m-%d %H:%M")


def ask_conflict(action, local_entry, remote_entry):
    """Returns (choice, apply_to_all). Uppercase answers apply to all remaining."""
    remote_epoch = engine.drive_time_to_epoch(remote_entry.get("modified"))
    print(f"\nCONFLICT: {action.relpath}")
    print(f"   local : {local_entry['size']:>10,} B   {_readable(local_entry.get('mtime'))}")
    print(f"   Drive : {remote_entry['size']:>10,} B   {_readable(remote_epoch)}")
    if action.winner:
        print(f"   ({action.winner} is newer)")

    while True:
        answer = input(
            "   k = keep both        l = local wins        d = Drive wins        s = skip this one\n"
            "   K = keep both for all remaining    L = local wins for all remaining\n"
            "   D = Drive wins for all remaining   S = skip all remaining\n"
            "   choice: "
        ).strip()

        if answer in VALID_CHOICES:
            return VALID_CHOICES[answer]
        print(f"   '{answer}' isn't one of the options.")
        print("   k = keep both        l = local wins        d = Drive wins        s = skip this one")
        print("   K = keep both for all remaining    L = local wins for all remaining")
        print("   D = Drive wins for all remaining   S = skip all remaining")


