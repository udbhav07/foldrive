"""Fixtures shared across the suite.

The layout mirrors what each layer needs from the outside world:

    unit/         nothing - pure functions, dicts in and out
    integration/  a FakeDrive standing in for the Drive API
    cli/          nothing but argparse
    platform/     a fake subprocess.run
    property/     randomized runs over the same FakeDrive
"""

import json

import pytest

from foldrive import config, state

from .helpers.fake_drive import FakeDrive, install

# foldrive ignores its own files in real use, and the tests must do the same -
# otherwise the harness syncs state.json into the fake Drive and nothing settles.
IGNORE = [".foldrive/", ".googledrive.json"]


@pytest.fixture
def fake_drive(monkeypatch):
    """An in-memory Drive, with drive.* pointed at it for the whole test."""
    fake = FakeDrive()
    install(fake, monkeypatch)
    return fake


@pytest.fixture
def synced_folder(tmp_path):
    """A folder that has been through `foldrive init`: config written, no state.

    Returns the path. Tests that need a snapshot call state.save_state themselves,
    because "never synced" and "synced once" are genuinely different situations.
    """
    (tmp_path / config.CONFIG_NAME).write_text(
        json.dumps({
            "drive_folder_id": "root",
            "drive_folder_name": "test-folder",
            "ignore": IGNORE,
        }),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def empty_state():
    """A fresh snapshot dict, the shape executor and the commands expect."""
    return {**state.EMPTY_STATE, "files": {}, "folders": {}}
