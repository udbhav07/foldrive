"""An in-memory stand-in for Google Drive.

Lets the full sync cycle run thousands of times with no network, which is what
makes randomized convergence testing practical. Implements the surface foldrive
actually uses; file contents are held as bytes in a dict.
"""

import hashlib
import itertools
from pathlib import Path, PurePosixPath

from foldrive import drive


class FakeDrive:
    def __init__(self):
        self.files = {}                  # relpath -> {id, content, modified}
        self.folders = {"": "root"}
        self._ids = itertools.count(1)
        self._clock = itertools.count(1)

    # --- helpers used by tests -------------------------------------------
    def _now(self):
        return f"2026-08-12T00:00:{next(self._clock):02}.000Z"

    def put(self, relpath, content, modified=None):
        """Write a file as if someone edited it in the Drive web UI."""
        self.files[relpath] = {
            "id": self.files.get(relpath, {}).get("id") or f"fake-{next(self._ids):06}",
            "content": content,
            "modified": modified or self._now(),
        }

    def contents(self):
        return {path: entry["content"] for path, entry in self.files.items()}

    # --- the drive.py surface --------------------------------------------
    def list_tree(self, service, folder_id):
        files = {
            relpath: {
                "id": entry["id"],
                "size": len(entry["content"]),
                "md5": hashlib.md5(entry["content"]).hexdigest(),
                "modified": entry["modified"],
            }
            for relpath, entry in self.files.items()
        }
        return files, dict(self.folders), 0

    def upload(self, service, local_path, parent_id, name):
        relpath = self._relpath_for(parent_id, name)
        self.put(relpath, Path(local_path).read_bytes())
        return self._result(relpath)

    def update(self, service, file_id, local_path):
        relpath = self._relpath_by_id(file_id)
        self.put(relpath, Path(local_path).read_bytes())
        return self._result(relpath)

    def download(self, service, file_id, destination_path):
        relpath = self._relpath_by_id(file_id)
        Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
        Path(destination_path).write_bytes(self.files[relpath]["content"])

    def trash(self, service, file_id):
        del self.files[self._relpath_by_id(file_id)]

    def create_folder(self, service, folder_name, parent_id=None):
        folder_id = f"fake-{next(self._ids):06}"
        self.folders[folder_name] = folder_id
        return folder_id

    def rename(self, service, file_id, new_name):
        relpath = self._relpath_by_id(file_id)
        entry = self.files.pop(relpath)
        parent = str(PurePosixPath(relpath).parent)
        entry["modified"] = self._now()
        self.files[f"{parent}/{new_name}" if parent != "." else new_name] = entry

    # --- internals -------------------------------------------------------
    def _result(self, relpath):
        entry = self.files[relpath]
        return {"id": entry["id"], "modifiedTime": entry["modified"],
                "md5Checksum": hashlib.md5(entry["content"]).hexdigest(),
                "size": len(entry["content"])}

    def _relpath_by_id(self, file_id):
        for relpath, entry in self.files.items():
            if entry["id"] == file_id:
                return relpath
        raise KeyError(f"no fake file with id {file_id}")

    def _relpath_for(self, parent_id, name):
        for folder_relpath, folder_id in self.folders.items():
            if folder_id == parent_id and folder_relpath:
                return f"{folder_relpath}/{name}"
        return name


def install(fake, monkeypatch):
    """Point drive.* at the fake for the duration of one test."""
    for name in ("list_tree", "upload", "update", "download", "trash",
                 "create_folder", "rename"):
        monkeypatch.setattr(drive, name, getattr(fake, name))
