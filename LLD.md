# foldrive — Low-Level Design

Companion to [PLAN.md](PLAN.md) (the what/why). This document is the how:
modules, function signatures, data schemas, algorithms, and flows. Code
bodies are intentionally absent — writing them is the project.

---

## 1. Architecture overview

```
                 ┌────────────────────────────────────────────────┐
                 │                    cli.py                      │
                 │   argparse dispatch: one cmd_* per subcommand  │
                 └──┬──────────┬──────────┬──────────┬────────────┘
                    │          │          │          │
              ┌─────▼───┐ ┌────▼────┐ ┌───▼────┐ ┌───▼──────────┐
              │ auth.py │ │config.py│ │engine.py│ │ scheduler.py │
              │ oauth + │ │ folder  │ │ 3-way   │ │ tick logic + │
              │ token   │ │ config +│ │ diff +  │ │ connectivity │
              │ cache   │ │ registry│ │ execute │ │ check        │
              └─────┬───┘ └─────────┘ └─┬──┬──┬─┘ └───┬──────────┘
                    │                   │  │  │       │
                    │            ┌──────▼┐┌▼──────┐┌──▼──────────┐
                    │            │drive  ││scanner││ autostart.py│
                    └───────────▶│.py    ││.py    ││ schtasks    │
                                 │Drive  ││local  ││ registration│
                                 │API    ││walk   │└─────────────┘
                                 │wrapper││+ md5  │
                                 └───┬───┘└───────┘   state.py
                                     ▼                (snapshot I/O,
                              Google Drive v3          used by engine)
```

Dependency rule: `cli` may import everything; `engine` imports `drive`,
`scanner`, `state`, `config`; nothing imports `cli`. `engine.classify()` is
pure (no I/O) so it is unit-testable.

---

## 2. On-disk data stores

### 2.1 Per synced folder

| Path | Owner | Purpose |
|---|---|---|
| `<folder>\.googledrive.json` | user-editable | pairing + schedule + policies |
| `<folder>\.foldrive\state.json` | machine | last-synced snapshot + cursors |

**`.googledrive.json`** (written by `init`, read by everything):

```json
{
  "drive_folder_id": "1AbC...xyz",
  "drive_folder_name": "7th sem",
  "schedule": { "pull_every_minutes": 30, "push_every_minutes": 50 },
  "ignore": [".foldrive/", ".googledrive.json", "~$*", "*.tmp", "desktop.ini",
             "Thumbs.db", ".DS_Store", ".venv/", "venv/", "env/", "__pycache__/",
             "*.pyc", "node_modules/", ".git/", ".idea/", ".vscode/",
             "build/", "dist/", "*.egg-info/"],
  "conflict_policy": "ask",
  "delete_policy": "trash"
}
```

**`.foldrive\state.json`**:

```json
{
  "files": {
    "notes/CN_unit3.pdf": {
      "size": 123456,
      "mtime": 1753600000.123,
      "md5": "9e107d9d372bb6826bd81d3542a419d6",
      "drive_file_id": "1Qw...",
      "drive_modified": "2026-07-27T12:00:00.000Z"
    }
  },
  "folders": { "notes": "1Fo..." },
  "changes_page_token": "12345",
  "last_pull_ok": "2026-07-27T12:00:00Z",
  "last_push_ok": "2026-07-27T12:30:00Z"
}
```

Keys of `files` are **relative paths with forward slashes** (normalize
`\` → `/` at the scanner boundary so state is portable and comparable with
Drive paths).

### 2.2 Per machine (`%APPDATA%\foldrive\`)

| File | Purpose |
|---|---|
| `client_secret.json` | OAuth app identity (user-provided or bundled fallback) |
| `token.json` | this user's grant; created by `login` |
| `folders.json` | registry: list of absolute paths of all init-ed folders |
| `logs\foldrive.log` | rotating log (milestone 5) |

---

## 3. Module specifications

### 3.1 `auth.py` — identity

```python
SCOPES = ["https://www.googleapis.com/auth/drive"]
APP_DIR, TOKEN_PATH, CLIENT_SECRET_PATH  # Path constants

def get_credentials() -> Credentials | None
    # cached token -> load -> valid? return; expired+refreshable? refresh, resave, return; else None

def login() -> Credentials
    # get_credentials() or InstalledAppFlow(client secret).run_local_server(port=0); save to_json()

def get_service(creds=None) -> googleapiclient Resource
    # build("drive", "v3", credentials=...); SystemExit with hint if not logged in
```

Client-secret resolution order: `%APPDATA%` file → bundled package resource →
`SystemExit` printing the Cloud Console walkthrough.

### 3.2 `config.py` — folder config + registry

```python
CONFIG_NAME = ".googledrive.json"

def load_config(folder: Path) -> dict          # parse + validate + fill defaults
def save_config(folder: Path, cfg: dict) -> None
def find_config_root(start: Path) -> Path | None   # walk upward like git does
def register_folder(folder: Path) -> None      # add to %APPDATA%\foldrive\folders.json
def registered_folders() -> list[Path]         # prune entries whose path no longer exists
```

Validation rules: `drive_folder_id` non-empty; intervals positive ints;
unknown keys warn, don't crash (forward compatibility).

### 3.3 `state.py` — snapshot I/O

```python
def load_state(folder: Path) -> dict           # missing file -> empty skeleton dict
def save_state(folder: Path, st: dict) -> None # write temp file, then os.replace (atomic)
```

Atomic write matters: a crash mid-save must never corrupt the snapshot.

### 3.4 `scanner.py` — local truth

```python
def scan(folder: Path, ignore: list[str], prev_files: dict) -> dict[str, LocalFile]
# LocalFile: {"size": int, "mtime": float, "md5": str}
```

Algorithm: `os.walk`; skip ignored names (`fnmatch` per path component and
whole relpath; entries ending `/` match directories). md5 optimization:
if relpath in `prev_files` and size+mtime unchanged → reuse stored md5;
else hash in 1 MiB chunks. OneDrive placeholder guard: skip files with the
`FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` bit (0x400000 in `st_file_attributes`)
and print a notice.

### 3.5 `drive.py` — remote truth (thin wrapper, no sync logic)

```python
def find_folder_by_name(svc, name: str) -> list[dict]        # q: mimeType folder, name=, not trashed
def create_folder(svc, name: str, parent_id: str | None) -> str
def list_tree(svc, folder_id: str) -> dict[str, RemoteFile]  # BFS; returns relpath -> meta
# RemoteFile: {"id", "size": int, "md5": str|None, "modified": str, "mimeType": str}
def upload(svc, local_path: Path, parent_id: str, name: str) -> dict     # files().create + MediaFileUpload(resumable)
def update(svc, file_id: str, local_path: Path) -> dict                  # files().update, same id
def download(svc, file_id: str, dest: Path) -> None                      # MediaIoBaseDownload -> temp file -> os.replace
def trash(svc, file_id: str) -> None                                     # files().update(body={"trashed": True})
def changes_start_token(svc) -> str
def changes_since(svc, token: str) -> tuple[list[dict], str]             # (changes, new_token)
```

Conventions: every list call passes explicit
`fields="files(id,name,mimeType,size,md5Checksum,modifiedTime,parents)"`
and handles `nextPageToken` pagination. Google-native files
(`mimeType` starts `application/vnd.google-apps`, except `.folder`) are
excluded with a counter reported to the caller.

### 3.6 `engine.py` — the heart

```python
@dataclass
class Action:
    kind: str        # one of the classification results below
    relpath: str
    reason: str      # human-readable, shown by status
    winner: str = "" # conflicts only: "local" | "drive" | "" (tie)

def classify(local: dict, remote: dict, snapshot: dict) -> list[Action]   # PURE — no I/O
def downgrade_for_first_sync(actions) -> list[Action]   # deletions -> keeps; drops `forget`
def drive_time_to_epoch(rfc3339: str) -> float | None   # Drive text time -> comparable float
def decide_conflict_winner(local_entry, remote_entry) -> str    # "local" | "drive" | ""
def conflict_copy_name(relpath, side, taken_names=()) -> str    # pure; collisions numbered
def execute_push(svc, folder, cfg, st, actions) -> Summary
def execute_pull(svc, folder, cfg, st, actions) -> Summary
def first_sync_confirm(actions) -> bool    # print full plan, input("proceed? [y/N] ")
```

`classify` and `downgrade_for_first_sync` are a **pipeline, not alternatives**:
callers always classify, then downgrade only when `state["files"]` is empty.

**Classification truth table.** For each relpath in
`local ∪ remote ∪ snapshot` (S = in snapshot, L = in local, R = in remote;
"changed" = md5 differs from snapshot's md5):

| S | L | R | condition | action |
|---|---|---|---|---|
| ✗ | ✓ | ✗ | — | `upload_new` |
| ✗ | ✗ | ✓ | — | `download_new` |
| ✗ | ✓ | ✓ | same md5 | `link` (adopt into snapshot, no transfer) |
| ✗ | ✓ | ✓ | different md5 | `conflict` |
| ✓ | ✓ | ✓ | L changed, R unchanged | `upload_changed` |
| ✓ | ✓ | ✓ | L unchanged, R changed | `download_changed` |
| ✓ | ✓ | ✓ | both changed | `conflict` |
| ✓ | ✓ | ✓ | neither | `noop` |
| ✓ | ✗ | ✓ | R unchanged | `trash_remote` (local delete wins) |
| ✓ | ✗ | ✓ | R changed | `download_new` (edit beats delete — safety) |
| ✓ | ✓ | ✗ | L unchanged | `recycle_local` (remote delete wins) |
| ✓ | ✓ | ✗ | L changed | `upload_new` (edit beats delete) |
| ✓ | ✗ | ✗ | — | `forget` (drop from snapshot) |

**Conflict resolution.** `decide_conflict_winner()` compares local `mtime`
against Drive's `modifiedTime` (parsed by `drive_time_to_epoch`) and returns
`"local"`, `"drive"`, or `""`. The two values come from different clocks, so a
difference within `TIE_WINDOW_SECONDS` (5) is a tie — no winner, keep both.
The `Action.winner` field carries this to the executor and to `status`.

The winner keeps the original name. The other version is written to both sides
under `conflict_copy_name(relpath, side)` → `<stem> (<side> copy)<ext>`, e.g.
`notes (local copy).docx`, bumped to `(local copy 2)` on collision. The `side`
label names where that version came from, not who lost. Both files exist on
both sides afterwards; nothing is deleted.

`conflict_policy` values:
- `"ask"` (default) — prompt per conflict when stdin is a terminal:
  `[k]eep both / [l]ocal wins / [d]rive wins / [s]kip / [K]eep both for all remaining`
- `"keep_both"` — never prompt

`tick` always behaves as `"keep_both"` regardless of config: a scheduled task
has no one to answer a prompt, and blocking on input would hang it forever.
Detect with `sys.stdin.isatty()`; `--yes` forces non-interactive for scripts.
Every run prints the conflict copies it created so they can be reviewed.

Direction filters: `push` executes {upload_new, upload_changed, trash_remote,
link, forget}; `pull` executes {download_new, download_changed, recycle_local,
link, forget}; conflicts execute in whichever direction runs first (they
touch both sides). Snapshot entry is updated **immediately after each
successful action**, then saved once at the end *and* on exception
(try/finally) — an interrupted sync resumes cleanly.

First-sync detection: `state["files"] == {}` → require `first_sync_confirm`.
On first sync every `trash_remote`/`recycle_local`/`forget` is downgraded to
`link`/`noop` — **nothing is deleted on a first sync**.

### 3.7 `scheduler.py`

```python
def is_online(timeout=2.0) -> bool     # HTTPS HEAD to www.googleapis.com
def tick() -> None
    # if not is_online(): return silently
    # for each registered folder: load cfg+state;
    #   overdue(last_pull_ok, pull_every_minutes) -> run pull (no confirm; skip if first sync pending)
    #   overdue(last_push_ok, push_every_minutes) -> run push
    # update last_*_ok ONLY on success  <- this is the offline-recovery mechanism
```

Timestamps are UTC ISO-8601 (`datetime.now(timezone.utc)`). A folder whose
sync fails stays overdue and retries next tick automatically.

### 3.8 `autostart.py`

```python
def install() -> None    # schtasks /create /sc minute /mo 5 /tn "foldrive-tick"
                         #   /tr "<venv-or-installed foldrive.exe> tick" /f
def uninstall() -> None  # schtasks /delete /tn "foldrive-tick" /f
def status() -> str      # schtasks /query /tn "foldrive-tick"
```

Resolve the exe path with `shutil.which("foldrive")` at install time.

### 3.9 `cli.py` — wiring (exists)

`init` flow: refuse if config already exists → refuse nested inside another
synced folder (`find_config_root`) → `find_folder_by_name(cwd.name)` →
0 hits: offer create; 1 hit: confirm; >1: numbered choice → write config →
`register_folder` → print counts + "run `foldrive sync`".

`status` flow (read-only — loads state, never saves it): `find_config_root` →
`load_config` → `load_state` → `scan` + `list_tree` → `classify` (+ downgrade
on first sync) → print. Output is **summarized**: one line per action kind with
a count, then the first 40 affected paths, then `... and N more`. The `--all`
flag lists every path. Any output that scales with folder size needs this cap —
a 5000-file folder otherwise scrolls the useful summary off screen.

Exit codes: 0 ok / 1 error / 2 nothing-to-do (argparse's own usage errors
also exit 2). Errors raise `SystemExit("message")` — no tracebacks for
expected failures.

---

## 4. Sequence flows

**push** (pull is the mirror image):

```
cli.cmd_push
 └─ config.find_config_root + load_config
 └─ auth.get_service
 └─ state.load_state
 └─ scanner.scan(folder, cfg.ignore, state.files)      # local truth
 └─ drive.list_tree(svc, cfg.drive_folder_id)          # remote truth
 └─ engine.classify(local, remote, state.files)        # plan
 └─ first sync?  engine.first_sync_confirm(plan) or abort
 └─ engine.execute_push(...)                           # transfers + snapshot updates
 └─ state.save_state; print Summary; set last_push_ok
```

**tick**: `scheduler.tick` → per folder, same as push/pull minus the
confirmation (first-sync folders are skipped with a log line — a human must
run the first sync).

---

## 5. Error-handling strategy

| Failure | Behavior |
|---|---|
| No internet mid-sync | current file fails → summary lists it; snapshot keeps prior state; next run retries |
| 401/invalid_grant | token revoked → delete token.json, message "run foldrive login" |
| 403 rate limit / 5xx | retry with exponential backoff (2s, 4s, 8s; then give up on that file) |
| File locked/open locally | skip with warning in summary; retried next run |
| state.json corrupt | refuse to guess: error telling user to delete `.foldrive\` and re-run (first-sync merge re-links everything safely) |
| Path > 260 chars | prefix `\\?\` on absolute paths (Windows long-path) |

---

## 6. Testing

- `tests/test_engine.py` — pytest over `classify()`: one test per truth-table
  row, plus first-sync downgrade rules. Pure dicts in, actions out; no mocks.
- `tests/test_scanner.py` — tmp_path fixtures: ignores, md5 reuse, rename.
- Manual E2E per milestone (see PLAN.md verification section).

---

## 7. Security notes

- `token.json` is the only secret at rest; never leaves the machine, never
  committed (`.gitignore`).
- Bundled `client_secret.json` grants nothing by itself (desktop-app secrets
  are not confidential by design; rclone precedent).
- All Drive access is scoped to the signed-in user's own account; foldrive
  has no server component and phones home to nothing but `googleapis.com`.
