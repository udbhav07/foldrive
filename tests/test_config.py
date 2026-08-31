"""Config loading and the two normalisers.

Both normalisers accept either a single value or a per-key object and always
return the dict form, so nothing downstream handles two shapes. Every rejection
is a SystemExit carrying the config path, because these are user-edited files.
"""

import json

import pytest

from foldrive import engine
from foldrive.config import (
    CONFIG_NAME,
    DEFAULT_DELETE_POLICY,
    DEFAULT_GOOGLE_NATIVE,
    GOOGLE_NATIVE_MODES,
    _normalise_delete_policy,
    _normalise_google_native,
    find_config_root,
    load_config,
)

CONFIG_PATH = "/somewhere/.googledrive.json"


def write_config(folder, **overrides):
    """A valid config with drive_folder_id filled in, plus whatever the test needs."""
    body = {"drive_folder_id": "drive-123", **overrides}
    (folder / CONFIG_NAME).write_text(json.dumps(body), encoding="utf-8")
    return folder


# --- the delete-side mapping -------------------------------------------------
#
# The highest-consequence pair of lines in the project: each deletion kind names
# the side the file is removed FROM. Inverting them would reverse the user's
# delete guarantee silently — never_delete on "drive" would start trashing files
# in Drive — and every test below would still pass.

def test_trash_remote_deletes_from_drive():
    assert engine.DELETE_SIDE["trash_remote"] == "drive"


def test_recycle_local_deletes_from_local():
    assert engine.DELETE_SIDE["recycle_local"] == "local"


def test_no_other_kind_counts_as_a_deletion():
    assert set(engine.DELETE_SIDE) == {"trash_remote", "recycle_local"}


# --- _normalise_delete_policy ------------------------------------------------

def test_delete_policy_defaults_when_absent():
    assert _normalise_delete_policy(None, CONFIG_PATH) == DEFAULT_DELETE_POLICY


def test_delete_policy_bare_string_applies_to_both_sides():
    assert _normalise_delete_policy("never_delete", CONFIG_PATH) == {
        "local": "never_delete", "drive": "never_delete",
    }


def test_delete_policy_per_side_object_is_kept():
    assert _normalise_delete_policy({"drive": "never_delete"}, CONFIG_PATH) == {
        "local": "trash", "drive": "never_delete",
    }


def test_delete_policy_rejects_an_unknown_policy_name():
    with pytest.raises(SystemExit, match="unknown delete_policy"):
        _normalise_delete_policy("delete_forever", CONFIG_PATH)


def test_delete_policy_rejects_an_unknown_side():
    with pytest.raises(SystemExit, match="unknown delete_policy side"):
        _normalise_delete_policy({"remote": "trash"}, CONFIG_PATH)


def test_delete_policy_rejects_an_unknown_policy_for_a_known_side():
    with pytest.raises(SystemExit, match="unknown delete_policy"):
        _normalise_delete_policy({"drive": "shred"}, CONFIG_PATH)


def test_delete_policy_rejects_a_non_object():
    with pytest.raises(SystemExit, match="must be a policy name or an object"):
        _normalise_delete_policy(["trash"], CONFIG_PATH)


def test_delete_policy_does_not_mutate_the_default():
    _normalise_delete_policy({"drive": "never_delete"}, CONFIG_PATH)
    assert DEFAULT_DELETE_POLICY == {"local": "trash", "drive": "trash"}


# --- _normalise_google_native ------------------------------------------------

def test_google_native_defaults_when_absent():
    assert _normalise_google_native(None, CONFIG_PATH) == DEFAULT_GOOGLE_NATIVE


@pytest.mark.parametrize("mode", sorted(GOOGLE_NATIVE_MODES))
def test_google_native_bare_string_applies_to_every_type(mode):
    assert _normalise_google_native(mode, CONFIG_PATH) == {
        "docs": mode, "sheets": mode, "slides": mode,
    }


def test_google_native_per_type_object_is_kept():
    assert _normalise_google_native({"sheets": "two_way"}, CONFIG_PATH) == {
        "docs": "download_only", "sheets": "two_way", "slides": "download_only",
    }


def test_google_native_rejects_an_unknown_mode():
    with pytest.raises(SystemExit, match="unknown google_native mode"):
        _normalise_google_native("sync_everything", CONFIG_PATH)


def test_google_native_rejects_an_unknown_type():
    with pytest.raises(SystemExit, match="unknown google_native type"):
        _normalise_google_native({"forms": "skip"}, CONFIG_PATH)


def test_google_native_rejects_an_unknown_mode_for_a_known_type():
    with pytest.raises(SystemExit, match="unknown google_native mode"):
        _normalise_google_native({"docs": "sync_everything"}, CONFIG_PATH)


def test_google_native_rejects_a_non_object():
    with pytest.raises(SystemExit, match="must be a mode name or an object"):
        _normalise_google_native(42, CONFIG_PATH)


def test_google_native_does_not_mutate_the_default():
    _normalise_google_native({"sheets": "two_way"}, CONFIG_PATH)
    assert DEFAULT_GOOGLE_NATIVE["sheets"] == "skip"


# --- load_config -------------------------------------------------------------

def test_load_config_fills_in_the_defaults(tmp_path):
    write_config(tmp_path)
    loaded = load_config(tmp_path)
    assert loaded["conflict_policy"] == "ask"
    assert loaded["max_delete_percent"] == 25
    assert loaded["max_delete_minimum"] == 10
    assert ".foldrive/" in loaded["ignore"]


def test_load_config_keeps_what_the_user_set(tmp_path):
    write_config(tmp_path, conflict_policy="keep_both", max_delete_percent=90)
    loaded = load_config(tmp_path)
    assert loaded["conflict_policy"] == "keep_both"
    assert loaded["max_delete_percent"] == 90


def test_load_config_merges_the_schedule_one_key_at_a_time(tmp_path):
    """A user setting only pull_every_minutes must not lose the push default."""
    write_config(tmp_path, schedule={"pull_every_minutes": 5})
    schedule = load_config(tmp_path)["schedule"]
    assert schedule == {"pull_every_minutes": 5, "push_every_minutes": 50}


def test_load_config_normalises_both_policy_shapes(tmp_path):
    write_config(tmp_path, delete_policy="never_delete", google_native="two_way")
    loaded = load_config(tmp_path)
    assert loaded["delete_policy"] == {"local": "never_delete", "drive": "never_delete"}
    assert loaded["google_native"] == {
        "docs": "two_way", "sheets": "two_way", "slides": "two_way",
    }


def test_load_config_exits_when_there_is_no_config(tmp_path):
    with pytest.raises(SystemExit, match="Not a foldrive folder"):
        load_config(tmp_path)


def test_load_config_exits_on_bad_json(tmp_path):
    (tmp_path / CONFIG_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="not valid JSON"):
        load_config(tmp_path)


def test_load_config_exits_without_a_drive_folder_id(tmp_path):
    (tmp_path / CONFIG_NAME).write_text('{"drive_folder_name": "x"}', encoding="utf-8")
    with pytest.raises(SystemExit, match="no drive_folder_id"):
        load_config(tmp_path)


def test_load_config_exits_on_an_empty_drive_folder_id(tmp_path):
    write_config(tmp_path, drive_folder_id="")
    with pytest.raises(SystemExit, match="no drive_folder_id"):
        load_config(tmp_path)


# --- find_config_root --------------------------------------------------------

def test_find_config_root_finds_the_config_here(tmp_path):
    write_config(tmp_path)
    assert find_config_root(tmp_path) == tmp_path


def test_find_config_root_walks_upward(tmp_path):
    write_config(tmp_path)
    deep = tmp_path / "notes" / "sem7" / "cn"
    deep.mkdir(parents=True)
    assert find_config_root(deep) == tmp_path


def test_find_config_root_returns_none_at_the_top(tmp_path):
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert find_config_root(deep) is None


def test_find_config_root_stops_at_the_nearest_config(tmp_path):
    """Nested folders each with a config resolve to the closest one, like git."""
    write_config(tmp_path)
    inner = tmp_path / "inner"
    inner.mkdir()
    write_config(inner, drive_folder_id="drive-inner")
    deeper = inner / "deeper"
    deeper.mkdir()
    assert find_config_root(deeper) == inner
