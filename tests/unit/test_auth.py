import pytest

from foldrive import auth


def test_login_without_client_file_points_to_setup(tmp_path, monkeypatch):
    # A fresh machine has neither a token nor the OAuth client file. That should be
    # a hint to run setup, not a FileNotFoundError traceback from google-auth.
    monkeypatch.setattr(auth, "TOKEN_PATH", tmp_path / "token.json")
    monkeypatch.setattr(auth, "CLIENT_SECRET_PATH", tmp_path / "client_secret.json")

    with pytest.raises(SystemExit) as exit_info:
        auth.login()

    assert "foldrive setup" in str(exit_info.value)
