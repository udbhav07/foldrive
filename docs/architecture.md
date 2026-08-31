# foldrive — architecture

How the pieces fit: modules, data schemas, the diff algorithm, and the flow of
one sync. For *why* a given rule exists, see [design-decisions.md](design-decisions.md).

---

## 1. Module map

```
                              cli.py
                  argparse dispatch; one module per
                     subcommand under commands/
                                 |
        +---------------+--------+--------+----------------+
        |               |                 |                |
     auth.py        config.py          engine.py        scheduler.py
   OAuth + token   folder config      three-way diff    is_online() +
      cache         + registry          (PURE)          is_overdue()
        |               |                 |                |
        |               |            executor.py      autostart.py
        |               |          performs actions;   schtasks (Windows)
        |               |          the only half of    / cron (everything
        |               |          the diff that does       else)
        |               |          I/O
        |               |            /        \
        +---------------+---------- /          \
                                   /            \
                             drive.py         scanner.py
                          Drive v3 wrapper   os.walk + md5
                                   |               |
                            Google Drive      the local disk

  supporting: state.py (snapshot I/O) - history.py (per-folder journal)
              paths.py (per-OS locations) - logs.py (rotating log)
              progress.py (per-file output) - prompts.py (interactive answers)
```

**The layering that matters.** `engine.py` is pure: dicts in, `Action` objects
out, no network and no disk. Every decision about *what should happen* lives
there. `executor.py` performs those actions and owns every side effect. That
split is what makes the riskiest logic testable without a network, and it is the
one boundary not to blur.

Dependency rule: `cli` may import anything; nothing imports `cli`. `engine`
imports nothing from `drive`, `scanner` or `state` — it only receives their
output.

---

## 2. On-disk data

### 2.1 Per synced folder

| Path | Owner | Purpose |
|---|---|---|
| `<folder>/.googledrive.json` | user-editable | pairing, schedule, policies |
| `<folder>/.foldrive/state.json` | machine | last-synced snapshot |
| `<folder>/.foldrive/history.jsonl` | machine | append-only record of actions taken |

**`.googledrive.json`** — written by `init`, read by everything:

```json
{
  "drive_folder_id": "1AbC...xyz",
  "drive_folder_name": "7th sem",
  "schedule": { "pull_every_minutes": 30, "push_every_minutes": 50 },
  "ignore": [".foldrive/", ".googledrive.json", "~$*", "*.tmp", "..."],
  "conflict_policy": "ask",
  "conflict_overrides": {},
  "delete_policy": { "local": "trash", "drive": "trash" },
  "max_delete_percent": 25,
  "max_delete_minimum": 10,
  "google_native": { "docs": "download_only", "sheets": "skip", "slides": "download_only" }
}
```

`delete_policy` and `google_native` each accept either one value covering every
side or type, or a per-side / per-type object. `config.py` normalises both to
the dict form on load, so nothing downstream handles two shapes.

**`.foldrive/state.json`** — the snapshot the next run diffs against:

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
  "changes_page_token": null,
  "last_pull_ok": "2026-07-27T12:00:00+00:00",
  "last_push_ok": "2026-07-27T12:30:00+00:00"
}
```

Each entry carries both fingerprints — local size/mtime/md5 and Drive
id/modifiedTime — because the next run compares each side against them
independently. Keys are relative paths with forward slashes, so a snapshot
stays comparable with Drive's paths regardless of OS.

`save_state` writes a temp file and `os.replace`s it, so a crash during the save
leaves either the old snapshot or the new one, never a half-written one.

**`.foldrive/history.jsonl`** — one JSON object per line, appended after each
action succeeds. Halved once it passes `MAX_HISTORY_BYTES` (512 KB).

### 2.2 Per machine

`paths.py` resolves these once, through `platformdirs`:

| OS | Location |
|---|---|
| Windows | `%APPDATA%\foldrive` |
| macOS | `~/Library/Application Support/foldrive` |
| Linux | `~/.local/share/foldrive` (or `$XDG_DATA_HOME/foldrive`) |

| File | Purpose |
|---|---|
| `client_secret.json` | the OAuth client, installed by `foldrive setup` |
| `token.json` | this user's grant, created by `login` |
| `folders.json` | registry of every init-ed folder, by absolute path |
| `logs/foldrive.log` | rotating log, 1 MB x 3 |

---

## 3. The diff engine

### 3.1 Classification

`engine.classify(local_files, remote_files, snapshot_files)` walks the union of
the three key sets and returns a list of `Action(kind, relpath, reason, winner)`.
S = present in the snapshot, L = local, R = remote; "changed" means the md5
differs from the snapshot's.

| S | L | R | condition | action |
|---|---|---|---|---|
| no | yes | no | — | `upload_new` |
| no | no | yes | — | `download_new` |
| no | yes | yes | same md5 | `link` — adopt into the snapshot, no transfer |
| no | yes | yes | different md5 | `conflict` |
| yes | yes | yes | L changed only | `upload_changed` |
| yes | yes | yes | R changed only | `download_changed` |
| yes | yes | yes | both changed | `conflict` |
| yes | yes | yes | neither | nothing |
| yes | no | yes | R unchanged | `trash_remote` — the local delete wins |
| yes | no | yes | R changed | `download_new` — an edit beats a delete |
| yes | yes | no | L unchanged | `recycle_local` — the remote delete wins |
| yes | yes | no | L changed | `upload_new` — an edit beats a delete |
| yes | no | no | — | `forget` — drop it from the snapshot |

The two "edit beats a delete" rows are the safety rows: an edit is never
destroyed by a deletion on the other side.

Google Docs, Sheets and Slides get their own kinds (`download_new_doc`,
`upload_changed_doc`, `conflict_doc`, and so on) because they transfer through a
format conversion and compare on `modifiedTime` rather than md5. There is
deliberately no `upload_new_doc`: a local `.docx` with no counterpart in Drive is
an ordinary file and uploads as one. Docs are born in Drive.

### 3.2 The pipeline around it

`classify` is one stage, not the whole story. Callers run:

```
classify
  -> apply_google_native_mode   filter Doc actions by each type's mode
  -> downgrade_for_first_sync   only when the snapshot is empty
  -> apply_delete_policy        drop deletions on a never_delete side
  -> mass_delete_check          refuse an implausibly large deletion
  -> split by direction         UPLOAD_KINDS for push, DOWNLOAD_KINDS for pull
```

Order matters in two places. `apply_delete_policy` runs *before*
`mass_delete_check`, so deletions the policy already dropped cannot count toward
the guard's threshold. And `downgrade_for_first_sync` runs only when
`state["files"]` is empty — a first sync merges two unknown trees and must never
delete anything.

`DELETE_SIDE` maps each deletion kind to the side it removes a file *from*:
`trash_remote` -> `"drive"`, `recycle_local` -> `"local"`. Inverting that pair
would silently reverse the user's delete guarantee, which is why it is a named
constant with its own tests.

### 3.3 Conflicts

`decide_conflict_winner` compares the local mtime against Drive's
`modifiedTime`. The two come from different clocks, so anything inside
`TIE_WINDOW_SECONDS` (5) is a tie: no winner, keep both.

The winner keeps the original name; the other version is written to both sides
as `conflict_copy_name(relpath, side)` — `notes.docx` becomes
`notes (drive copy).docx`, numbered on collision. The `side` label says where
that version came from, not who lost. Nothing is deleted.

`conflict_policy` is `"ask"` (prompt per conflict, and only when stdin is a
terminal) or `"keep_both"` (never prompt). `conflict_overrides` holds standing
per-file answers, checked before any prompt. `tick` always behaves as
`keep_both`: a scheduled run has nobody to answer.

Every question is asked *before* the first transfer —
`executor.collect_conflict_choices` is pure decisions and
`apply_conflict_choices` performs them — so the user answers in the first few
seconds and the rest of the run needs no one watching it.

---

## 4. One sync, end to end

`push` (pull is the mirror image):

```
commands/push.run
 |- config.find_config_root      walk upward for .googledrive.json, like git
 |- config.load_config
 |- state.load_state
 |- auth.get_service
 |- scanner.scan(...)            local truth
 |- drive.list_tree(...)         remote truth
 |- engine.classify(...)         the plan, then the pipeline in 3.2
 |- executor.collect_conflict_choices   ask everything up front
 |- executor.push(...)           transfers; snapshot updated per success
 |- executor.apply_conflict_choices
 `- state.save_state             in a finally, so Ctrl-C keeps what finished
```

`sync` is `pull` followed by `push`. `tick` is the same minus every prompt, and
skips folders that have never been synced.

Mid-run, `executor` saves the snapshot every `SAVE_EVERY` (25) transfers. Each
file's entry is written the moment its own transfer succeeds, so the snapshot
always describes exactly the work that is finished — a killed process redoes at
most 24 files, and never creates duplicates.

Only success advances `last_pull_ok` / `last_push_ok`. That single rule is the
whole of offline recovery: a folder whose sync failed stays overdue and retries
on the next tick, with no recovery code anywhere.

---

## 5. Scheduling

`autostart.py` registers `foldrive tick` to run every 5 minutes — Task Scheduler
on Windows, cron everywhere else. `tick` then decides what is actually due:

```
is_online()?              a 2s TLS handshake, not a full API call
logged in?                say it once, not once per folder
for each registered folder:
    is_overdue(last_pull_ok, pull_every_minutes) -> pull
    is_overdue(last_push_ok, push_every_minutes) -> push
```

`tick` catches `(Exception, SystemExit)` per folder. `SystemExit` is a
`BaseException`, so a bare `except Exception` would let one corrupt config file
kill the tick for every remaining folder.

---

## 6. Error handling

| Failure | Behaviour |
|---|---|
| One file fails mid-run | counted in `failed` and printed; the rest continue, and it retries next run |
| Network drops | the timestamp stays stale, so the next tick retries |
| 403 / 429 / 5xx | retried by the API client (`num_retries=5`), then left for the next run |
| 404 on the Drive folder | logged as permanent: re-run `foldrive init` |
| Token revoked | `token.json` is deleted and the message says to run `foldrive login` |
| `state.json` corrupt | refuses to guess: delete `.foldrive/` and re-sync, which re-links both sides without deleting |
| An unreadable directory | `scanner` raises rather than omitting files — an omission is indistinguishable from a deletion |
| Ctrl-C | `SystemExit` with a message; the snapshot was already saved in a `finally` |

Expected failures raise `SystemExit("message")`. No tracebacks for things the
user can act on.

---

## 7. Security

- `token.json` is the only secret at rest. It never leaves the machine, and it
  is gitignored.
- There is no bundled OAuth client: each user installs their own through
  `foldrive setup`, so nobody shares a quota or a 100-user cap.
- All access is scoped to the signed-in user's own Drive. foldrive has no server
  component and talks to nothing but `googleapis.com`.

See [SECURITY.md](../SECURITY.md) for how to report a vulnerability.
