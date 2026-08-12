"""Show what foldrive did to this folder, most recent first."""

from datetime import datetime
from pathlib import Path

from .. import config, history

# Past tense: this is a record of what happened, not a plan.
KIND_LABELS = {
    "upload_new": "uploaded",
    "upload_changed": "updated in Drive",
    "download_new": "downloaded",
    "download_changed": "updated locally",
    "trash_remote": "trashed in Drive",
    "recycle_local": "moved to Recycle Bin",
    "link": "linked",
    "download_new_doc": "downloaded Doc",
    "download_changed_doc": "downloaded Doc again",
    "download_changed_doc_keep_local": "downloaded Doc, kept local copy",
    "upload_changed_doc": "uploaded into Doc",
    "upload_changed_doc_keep_drive": "uploaded into Doc, kept Drive copy",
    "restore": "restored from Drive",
}

# A gap this long means a different run - blank line between runs so the history
# reads as sessions rather than one undifferentiated stream.
RUN_GAP_SECONDS = 120


def _local_time(iso_text):
    try:
        return datetime.fromisoformat(iso_text).astimezone()
    except (ValueError, TypeError):
        return None


def run(args):
    folder = config.find_config_root(Path.cwd())
    if folder is None:
        raise SystemExit("Not a foldrive folder. Run: foldrive init")

    limit = None if args.all else args.number
    entries = history.read(folder, limit)

    if not entries:
        print("No history yet for this folder.")
        print("It is written as foldrive syncs; run `foldrive sync` first.")
        return

    print(f"Folder : {folder}")
    print(f"History: {history.history_path(folder)}\n")

    previous_time = None
    for entry in entries:
        moment = _local_time(entry.get("at"))
        if (previous_time and moment
                and (previous_time - moment).total_seconds() > RUN_GAP_SECONDS):
            print()
        previous_time = moment

        stamp = moment.strftime("%Y-%m-%d %H:%M:%S") if moment else "unknown time"
        label = KIND_LABELS.get(entry.get("kind"), entry.get("kind", "?"))
        print(f"  {stamp}  {label:<28} {entry.get('path', '')}")

    if not args.all:
        print(f"\nShowing the last {len(entries)}. Use --all for everything, "
              f"-n N for a different count.")
