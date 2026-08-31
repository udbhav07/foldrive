"""An in-memory stand-in for Google Drive.

Lets the full sync cycle run thousands of times with no network, which is what
makes randomized convergence testing practical. Implements the surface foldrive
actually uses; file contents are held as bytes in a dict.
"""

import hashlib
import itertools
from pathlib import Path, PurePosixPath

from foldrive import drive

# The extension each native type exports to, and the mimetypes list_tree reports.
# Mirrors drive.GOOGLE_NATIVE_EXPORTS, keyed the way the tests want to say it.
NATIVE_TYPES = {
    "docs": (
        "application/vnd.google-apps.document",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "sheets": (
        "application/vnd.google-apps.spreadsheet",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "slides": (
        "application/vnd.google-apps.presentation",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
}


class FakeDrive:
    def __init__(self):
        self.files = {}                  # relpath -> {id, content, modified}
        self.docs = {}                   # relpath (with export extension) -> doc entry
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

    def put_doc(self, name, content, native_type="docs", modified=None):
        """Create or edit a Google Doc/Sheet/Slides deck.

        `name` is the Drive name with no extension, exactly as a Doc has none.
        The relpath foldrive sees is that name plus the export extension, which
        is how drive.list_tree presents it.
        """
        _native_mime, _export_mime, extension = NATIVE_TYPES[native_type]
        relpath = name + extension
        self.docs[relpath] = {
            "id": self.docs.get(relpath, {}).get("id") or f"doc-{next(self._ids):06}",
            "content": content,
            "modified": modified or self._now(),
            "native_type": native_type,
        }
        return relpath

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
        for relpath, entry in self.docs.items():
            native_mime, export_mime, _extension = NATIVE_TYPES[entry["native_type"]]
            files[relpath] = {
                "id": entry["id"],
                "size": 0,
                "md5": None,               # natives have none; never compare on it
                "modified": entry["modified"],
                "is_google_native": True,
                "native_mime": native_mime,
                "export_mime": export_mime,
                "native_type": entry["native_type"],
            }
        return files, dict(self.folders), 0

    def download_native(self, service, file_id, export_mime, destination_path):
        """Google calls this 'export'. Deliberately not byte-stable: a real Doc
        exports to different bytes every time, which is the whole reason Docs
        compare on modifiedTime instead of md5."""
        relpath = self._doc_relpath_by_id(file_id)
        entry = self.docs[relpath]
        Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
        Path(destination_path).write_bytes(
            entry["content"] + f"\n<export {next(self._clock)}>".encode()
        )

    def upload_doc(self, service, file_id, local_path, native_mime):
        """A .docx sent back INTO the same Doc: same id, new modifiedTime."""
        relpath = self._doc_relpath_by_id(file_id)
        entry = self.docs[relpath]
        entry["content"] = Path(local_path).read_bytes()
        entry["modified"] = self._now()
        return {"id": entry["id"], "modifiedTime": entry["modified"]}

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
        """Drive is told a leaf name and a parent id, never a path - so the fake
        has to rebuild the relpath from the parent, exactly as list_tree would.
        Keying this by the leaf name alone puts `a/b/c.txt` at `b/c.txt`."""
        folder_id = f"fake-{next(self._ids):06}"
        parent_relpath = self._folder_relpath_by_id(parent_id)
        self.folders[
            f"{parent_relpath}/{folder_name}" if parent_relpath else folder_name
        ] = folder_id
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

    def _folder_relpath_by_id(self, folder_id):
        for folder_relpath, existing_id in self.folders.items():
            if existing_id == folder_id:
                return folder_relpath
        raise KeyError(f"no fake folder with id {folder_id}")

    def _doc_relpath_by_id(self, file_id):
        for relpath, entry in self.docs.items():
            if entry["id"] == file_id:
                return relpath
        raise KeyError(f"no fake Doc with id {file_id}")

    def _relpath_for(self, parent_id, name):
        for folder_relpath, folder_id in self.folders.items():
            if folder_id == parent_id and folder_relpath:
                return f"{folder_relpath}/{name}"
        return name


def install(fake, monkeypatch):
    """Point drive.* at the fake for the duration of one test."""
    for name in ("list_tree", "upload", "update", "download", "trash",
                 "create_folder", "rename", "download_native", "upload_doc"):
        monkeypatch.setattr(drive, name, getattr(fake, name))
