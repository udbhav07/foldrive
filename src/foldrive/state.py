import copy, json, os
from pathlib import Path




STATE_DIR_NAME = ".foldrive"
STATE_FILE_NAME = "state.json"

EMPTY_STATE = {
    "files": {},
    "folders":{},
    "changes_page_token": None,
    "last_pull_ok": None,
    "last_push_ok": None,
}


def state_path(folder):
    return Path(folder) / STATE_DIR_NAME / STATE_FILE_NAME


def load_state(folder):
    state_file_path = state_path(folder)
    if not state_file_path.exists():
        return copy.deepcopy(EMPTY_STATE)

    try:
        loaded_state = json.loads(state_file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as parse_error:
        raise SystemExit(
            f"{state_file_path} is corrupt ({parse_error}).\n"
            f"Delete the {STATE_DIR_NAME} folder and run `foldrive sync` - "
            "the first sync re-links both sides without deleting anything."
        )

    merged_state = copy.deepcopy(EMPTY_STATE)
    merged_state.update(loaded_state)
    return merged_state


def save_state(folder, state):
    state_file_path = state_path(folder)
    state_file_path.parent.mkdir(exist_ok=True)
    temporary_path = state_file_path.with_name(STATE_FILE_NAME + ".tmp")
    temporary_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temporary_path, state_file_path)