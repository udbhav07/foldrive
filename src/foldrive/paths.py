"""Where foldrive keeps its own files, on whichever OS it is running.

One module so the answer is defined once. Previously auth/config/logs each read
os.environ["APPDATA"] at import time, which raises KeyError off Windows - so
`foldrive --version` would traceback on Linux before main() ever ran.

    Windows  C:\\Users\\<you>\\AppData\\Roaming\\foldrive
    macOS    ~/Library/Application Support/foldrive
    Linux    ~/.local/share/foldrive   (or $XDG_DATA_HOME/foldrive)
"""

from pathlib import Path

from platformdirs import user_data_dir

# roaming=True keeps Windows on %APPDATA%. The platformdirs default is
# LOCALAPPDATA, which would silently orphan every existing install's token.json
# and folders.json - the user would appear logged out with no folders registered.
APP_DIR = Path(user_data_dir("foldrive", appauthor=False, roaming=True))

TOKEN_PATH = APP_DIR / "token.json"
REGISTRY_PATH = APP_DIR / "folders.json"

# Deliberately not platformdirs' user_log_dir: on Windows that resolves to
# LOCALAPPDATA\foldrive\Logs, moving logs away from where they already are.
LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "foldrive.log"
