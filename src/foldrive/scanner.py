import fnmatch
import hashlib
import os
import sys
from pathlib import Path

HASH_CHUNK_SIZE = 1024*1024 #1MiB

def _matches_any_pattern(name, patterns):
    return any(fnmatch.fnmatch(name,pattern) for pattern in patterns)

def _split_patterns(ignore_patterns):
    directory_patterns = []
    file_patterns = []
    for pattern in ignore_patterns:
        if(pattern.endswith("/")):
            directory_patterns.append(pattern.rstrip("/"))
        else:
            file_patterns.append(pattern)
    return directory_patterns, file_patterns

def compute_md5(file_path):
    hasher = hashlib.md5()
    with open(file_path,"rb") as open_file:
        while chunk := open_file.read(HASH_CHUNK_SIZE):
            hasher.update(chunk)
    return hasher.hexdigest()

def scan(folder,ignore_patterns, previous_files):
    """Return {relpath: {"size", "mtime", "md5"}} for every non-ignored file.

    previous_files is the snapshot's files dict; when a file's size and mtime
    are unchanged we trust its stored md5 instead of re-reading the bytes.
    """
    folder = Path(folder)
    directory_patterns,file_patterns = _split_patterns(ignore_patterns)
    scanned_files = {}

    def on_walk_error(walk_error):
        """os.walk ignores unreadable directories by default: they simply vanish
        from the results, which is indistinguishable from "those files were
        deleted" - so foldrive would trash them in Drive. Refuse instead of
        guessing, and name the directory that could not be read.
        """
        message = f"Cannot read {walk_error.filename}: {walk_error.strerror}"
        if sys.platform == "darwin":
            message += (
                "\n\nOn macOS, background tools need Full Disk Access to read "
                "~/Desktop, ~/Documents\nand ~/Downloads. Grant it to whatever runs "
                "foldrive:\n"
                "  System Settings -> Privacy & Security -> Full Disk Access -> +\n"
                "  -> Cmd-Shift-G -> /usr/sbin/cron   (and your terminal app, for "
                "manual runs)"
            )
        raise SystemExit(message)

    for current_directory, subdirectory_names, file_names in os.walk(folder, onerror=on_walk_error):
        subdirectory_names[:] = [
            name for name in subdirectory_names
            if not _matches_any_pattern(name, directory_patterns)
        ]

        for file_name in file_names:
            absolute_path = Path(current_directory)/file_name
            relative_path = absolute_path.relative_to(folder).as_posix()

            if _matches_any_pattern(file_name, file_patterns):
                continue
            if _matches_any_pattern(relative_path,file_patterns):
                continue

            try:
                file_stat = absolute_path.stat()
            except OSError:
                continue # vanished or unreadable between walk and stat

            size = file_stat.st_size
            mtime = file_stat.st_mtime

            previous_entry = previous_files.get(relative_path)
            if(
                previous_entry is not None 
                and previous_entry.get("size") == size
                and previous_entry.get("mtime") == mtime
            ):
                md5 = previous_entry["md5"]
            else:
                try:
                    md5 = compute_md5(absolute_path)
                except OSError:
                    continue

            scanned_files[relative_path] = {"size":size, "mtime":mtime, "md5":md5}
    return scanned_files



















