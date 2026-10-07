import json
from argparse import Namespace

import pytest
from google_auth_oauthlib.flow import InstalledAppFlow

from foldrive import auth, paths
from foldrive.commands import setup

CLIENT_ID = "1234-abc.apps.googleusercontent.com"


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "APP_DIR", tmp_path)
    monkeypatch.setattr(auth, "CLIENT_SECRET_PATH", tmp_path / "client_secret.json")
    return tmp_path


def answer(monkeypatch, *replies):
    replies = iter(replies)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))


def manual(force=False):
    return Namespace(path=None, force=force, manual=True)


def test_manual_writes_a_file_google_auth_accepts(app_dir, monkeypatch):
    answer(monkeypatch, f"  {CLIENT_ID} ", "GOCSPX-secret")

    setup.run(manual())

    # The real test is that login's loader takes it, same as a downloaded file.
    flow = InstalledAppFlow.from_client_secrets_file(str(auth.CLIENT_SECRET_PATH), auth.SCOPES)
    assert flow.client_config["client_id"] == CLIENT_ID
    assert flow.client_config["client_secret"] == "GOCSPX-secret"


def test_manual_rejects_swapped_fields(app_dir, monkeypatch):
    answer(monkeypatch, "GOCSPX-secret", CLIENT_ID)

    with pytest.raises(SystemExit, match="apps.googleusercontent.com"):
        setup.run(manual())
    assert not auth.CLIENT_SECRET_PATH.exists()


def test_manual_refuses_to_overwrite_without_force(app_dir, monkeypatch):
    auth.CLIENT_SECRET_PATH.write_text("{}", encoding="utf-8")
    answer(monkeypatch, CLIENT_ID, "GOCSPX-secret")

    with pytest.raises(SystemExit, match="--force"):
        setup.run(manual())

    setup.run(manual(force=True))
    assert json.loads(auth.CLIENT_SECRET_PATH.read_text())["installed"]["client_id"] == CLIENT_ID
