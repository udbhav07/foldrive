"""A per-folder record of what foldrive actually did.

The sync log answers "did the tick run?"; this answers "what did it do to my
files?" - which matters because most runs happen while nobody is watching.

One JSON object per line (JSONL) so appending is a single write with no parsing,
and a truncated last line from a crash costs one record instead of the whole file.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .state import STATE_DIR_NAME

HISTORY_FILE_NAME = "history.jsonl"

# Roughly a few thousand entries. Old history is nice to have, not worth letting a
# hidden file grow without limit inside someone's synced folder.
MAX_HISTORY_BYTES = 512 * 1024


def history_path(folder):
    return Path(folder) / STATE_DIR_NAME / HISTORY_FILE_NAME


def record(folder, kind, relative_path, drive_file_id=None):
    """Append one action. Never raises: losing a history line must not fail a sync."""
    entry = {
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "path": relative_path,
    }
    if drive_file_id:
        entry["drive_file_id"] = drive_file_id
    try:
        path = history_path(folder)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as history_file:
            history_file.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def trim_if_large(folder):
    """Drop the oldest half once the file gets big. Called once per run, not per
    file, so the cost is a single stat in the common case."""
    path = history_path(folder)
    try:
        if not path.exists() or path.stat().st_size <= MAX_HISTORY_BYTES:
            return
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[len(lines) // 2:]) + "\n", encoding="utf-8")
    except OSError:
        pass


def read(folder, limit=None):
    """Newest first. Skips malformed lines rather than failing - a half-written
    line from a killed process should not make the whole history unreadable."""
    path = history_path(folder)
    if not path.exists():
        return []

    entries = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []

    entries.reverse()
    return entries[:limit] if limit else entries
