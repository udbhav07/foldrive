import json
import os
from pathlib import Path

CONFIG_NAME = ".googledrive.json"
REGISTRY_PATH = Path(os.environ["APPDATA"]) / "foldrive" / "folders.json"

DEFAULT_CONFIG = {
    "drive_folder_id": "",
    "drive_folder_name": "",
    "schedule":
        {
            "pull_every_minutes":30,
            "push_every_minutes":50
        },
    "ignore": [
        # foldrive's own files
        ".foldrive/",
        ".googledrive.json",
        # editor / OS clutter
        "~$*",
        "*.tmp",
        "desktop.ini",
        "Thumbs.db",
        ".DS_Store",
        # developer junk: rebuildable, huge, and pointless in Drive
        ".venv/",
        "venv/",
        "env/",
        "__pycache__/",
        "*.pyc",
        "node_modules/",
        ".git/",
        ".idea/",
        ".vscode/",
        "build/",
        "dist/",
        "*.egg-info/",
    ],
    # "ask" prompts per conflict in a terminal; "keep_both" never prompts.
    # Scheduled runs (foldrive tick) always behave as "keep_both".
    "conflict_policy": "ask",
    # Per-file standing answers, e.g. {"notes/scratch.txt": "local"}.
    # Checked before prompting; values: keep_both | local | drive | skip.
    "conflict_overrides": {},
    # Per side, naming the side a file is deleted FROM. See _normalise_delete_policy.
    "delete_policy": {"local": "trash", "drive": "trash"},
    # Safety net against bugs that make one side look empty. A run is refused when
    # it would delete at least max_delete_minimum files AND at least
    # max_delete_percent of that side. Set max_delete_percent to 0 to disable.
    "max_delete_percent": 25,
    "max_delete_minimum": 10,
    # Google Docs/Sheets/Slides, per type. See _normalise_google_native below.
    "google_native": {"docs": "download_only", "sheets": "skip", "slides": "download_only"},
}

DELETE_POLICIES = {
    "trash",         # deletions propagate, recoverably (Recycle Bin / Drive trash)
    "never_delete",  # deletions never propagate; the other side keeps the file
}
# The key names the side a file is deleted FROM: "drive" governs trashing files in
# Drive, "local" governs recycling local files. Getting this backwards would
# silently invert the guarantee, so it is spelled out here and unit-tested.
DELETE_SIDES = ("local", "drive")
DEFAULT_DELETE_POLICY = {"local": "trash", "drive": "trash"}


def _normalise_delete_policy(raw_value, config_path):
    """Accepts one policy name for both sides, or a per-side object.
    Always returns the per-side dict, so no caller handles two shapes."""
    if raw_value is None:
        return dict(DEFAULT_DELETE_POLICY)

    if isinstance(raw_value, str):
        if raw_value not in DELETE_POLICIES:
            raise SystemExit(
                f'{config_path}: unknown delete_policy "{raw_value}". '
                f'Valid policies: {", ".join(sorted(DELETE_POLICIES))}.'
            )
        return {side: raw_value for side in DELETE_SIDES}

    if not isinstance(raw_value, dict):
        raise SystemExit(
            f'{config_path}: "delete_policy" must be a policy name or an object '
            f'with the keys {", ".join(DELETE_SIDES)}.'
        )

    policies = dict(DEFAULT_DELETE_POLICY)
    for side, policy in raw_value.items():
        if side not in DELETE_SIDES:
            raise SystemExit(
                f'{config_path}: unknown delete_policy side "{side}". '
                f'Valid sides: {", ".join(DELETE_SIDES)}.'
            )
        if policy not in DELETE_POLICIES:
            raise SystemExit(
                f'{config_path}: unknown delete_policy "{policy}" for {side}. '
                f'Valid policies: {", ".join(sorted(DELETE_POLICIES))}.'
            )
        policies[side] = policy
    return policies


GOOGLE_NATIVE_MODES = {"skip", "download_only", "upload_only", "two_way"}
GOOGLE_NATIVE_TYPES = ("docs", "sheets", "slides")

# Sheets default to skip: .xlsx cannot carry cross-sheet formulas, charts or
# filter views, so a round trip can quietly break a working spreadsheet.
DEFAULT_GOOGLE_NATIVE = {"docs": "download_only", "sheets": "skip", "slides": "download_only"}


def _normalise_google_native(raw_value, config_path):
    """Accepts a single mode name for all three types, or a per-type object.
    Always returns the per-type dict, so no caller handles two shapes."""
    if raw_value is None:
        return dict(DEFAULT_GOOGLE_NATIVE)

    if isinstance(raw_value, str):
        if raw_value not in GOOGLE_NATIVE_MODES:
            raise SystemExit(
                f'{config_path}: unknown google_native mode "{raw_value}". '
                f'Valid modes: {", ".join(sorted(GOOGLE_NATIVE_MODES))}.'
            )
        return {file_type: raw_value for file_type in GOOGLE_NATIVE_TYPES}

    if not isinstance(raw_value, dict):
        raise SystemExit(
            f'{config_path}: "google_native" must be a mode name or an object with '
            f'the keys {", ".join(GOOGLE_NATIVE_TYPES)}.'
        )

    modes = dict(DEFAULT_GOOGLE_NATIVE)
    for file_type, mode in raw_value.items():
        if file_type not in GOOGLE_NATIVE_TYPES:
            raise SystemExit(
                f'{config_path}: unknown google_native type "{file_type}". '
                f'Valid types: {", ".join(GOOGLE_NATIVE_TYPES)}.'
            )
        if mode not in GOOGLE_NATIVE_MODES:
            raise SystemExit(
                f'{config_path}: unknown google_native mode "{mode}" for {file_type}. '
                f'Valid modes: {", ".join(sorted(GOOGLE_NATIVE_MODES))}.'
            )
        modes[file_type] = mode
    return modes
def load_config(folder):
    config_path = Path(folder)/ CONFIG_NAME
    if not config_path.exists():
        raise SystemExit(f"Not a foldrive folder ({CONFIG_NAME} missing). Run: foldrive init")
    try:
        loaded_config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as parse_error:
        raise SystemExit(f"{config_path} is not valid JSON ({parse_error}). Fix it or delete it and re-run init")

    merged_config = {**DEFAULT_CONFIG, **loaded_config}
    merged_config["schedule"] ={**DEFAULT_CONFIG["schedule"], **loaded_config.get("schedule", {})}

    merged_config["google_native"] = _normalise_google_native(
        loaded_config.get("google_native"), config_path
    )
    merged_config["delete_policy"] = _normalise_delete_policy(
        loaded_config.get("delete_policy"), config_path
    )

    if not merged_config["drive_folder_id"]:
        raise SystemExit(f"{config_path} has no drive_folder_id. Re-run: foldrive init")
    return merged_config


def save_config(folder, config):
    config_path = Path(folder) / CONFIG_NAME
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    
def find_config_root(start):
    """Return the nearest folder (here or above) containing a config, else None."""
    for candidate_folder in [Path(start)] + list(Path(start).parents):
        if (candidate_folder / CONFIG_NAME).exists():
            return candidate_folder
    return None

def register_folder(folder):
    REGISTRY_PATH.parent.mkdir(exist_ok=True)
    registered_paths = []
    if REGISTRY_PATH.exists():
        registered_paths = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    folder_as_text = str(Path(folder).resolve())
    if folder_as_text not in registered_paths:
        registered_paths.append(folder_as_text)
        REGISTRY_PATH.write_text(json.dumps(registered_paths, indent=2), encoding="utf-8")

def registered_folders():
    """All registered folders that still exist on disk."""
    if not REGISTRY_PATH.exists():
        return []
    registered_paths = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return [Path(entry) for entry in registered_paths if Path(entry).exists()]












