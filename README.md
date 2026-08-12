<!-- Header block for project -->
<hr>

<div align="center">

<h1 align="center">foldrive</h1>

</div>

<pre align="center">Pair any local folder with any Google Drive folder, and sync them like git.</pre>

<!-- Header block for project -->

[![PyPI](https://img.shields.io/pypi/v/foldrive)](https://pypi.org/project/foldrive/) ![License](https://img.shields.io/badge/license-MIT-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Platforms](https://img.shields.io/badge/platforms-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey) [![SLIM](https://img.shields.io/badge/Best%20Practices%20from-SLIM-blue)](https://nasa-ammos.github.io/slim/)

```
$ foldrive status
Folder : C:\Users\me\Desktop\6th sem
Drive  : 6th sem
Local  : 336 files    Drive: 163 files

  CONFLICT         -> both sides changed        24 file(s)
  new in Drive     -> download                  25 file(s)
  new locally      -> upload                   198 file(s)
  identical        -> just remember it         114 file(s)

247 change(s) pending. Run `foldrive sync` to apply.
```

Google's own Drive for Desktop cannot map an arbitrary local folder — say
`Desktop\7th sem` — to an arbitrary My Drive folder like `My Drive/College/7th sem`.
It mirrors your whole Drive, or backs folders up into a separate "Computers"
section that your phone never sees. foldrive exists to fill exactly that gap, with
git-like explicit control: see what a sync *would* do, then do it.

It is built for people who want their files in a specific place on both sides, on a
schedule they choose, with nothing happening that they can't inspect first.

[Report an issue](https://github.com/udbhav07/foldrive/issues) | [Changelog](CHANGELOG.md)

## Features

* **Pair any two folders** — one local path, one Drive folder, in either direction.
* **Preview before acting** — `foldrive status` is read-only and shows every pending change.
* **Two-way sync** with conflict handling that never loses a version.
* **Background sync** on a per-folder schedule: Task Scheduler on Windows, cron on macOS and Linux.
* **Google Docs, Sheets and Slides** support, with four modes per file type.
* **Deletion safety** — soft deletes, a mass-delete guard, and an optional never-delete side.
* **Survives interruptions** — progress is checkpointed; re-running never creates duplicates.
* **Catches up automatically** after being offline, asleep, or unplugged.

## Contents

* [Quick Start](#quick-start)
* [How it behaves](#how-it-behaves)
* [Changelog](#changelog)
* [FAQ](#frequently-asked-questions-faq)
* [Contributing](#contributing)
* [License](#license)
* [Support](#support)

## Quick Start

### Requirements

* Python 3.10 or newer
* A Google account
* Windows, macOS or Linux

### Setup Instructions

1. Install foldrive:

   ```
   pip install foldrive
   ```

   <details>
   <summary>Or from source, to develop on it</summary>

   ```
   git clone https://github.com/udbhav07/foldrive && cd foldrive
   python -m venv .venv && .venv\Scripts\activate    # macOS/Linux: source .venv/bin/activate
   pip install -e .
   ```
   </details>

2. Create your own free Google OAuth client — `foldrive setup` prints the steps:

   ```
   foldrive setup
   ```

   Briefly: at <https://console.cloud.google.com> create a project, enable the
   **Google Drive API**, configure the **OAuth consent screen** (User type
   *External*, then **Publish app** — in "Testing" Google expires your login every
   7 days), then **Credentials → Create credentials → OAuth client ID →
   Application type "Desktop app"** and download the JSON.

   > Choose **Desktop app**, not Web application. A Web client cannot sign in from
   > a terminal.

3. Install the downloaded file and sign in:

   ```
   foldrive setup ~/Downloads/client_secret_xxxx.json
   foldrive login
   ```

   You will see Google's "unverified app" warning once — **Advanced → Go to
   foldrive → Allow**. That is expected for personal tools; verification is a paid
   audit intended for commercial apps.

### Run Instructions

1. Link a local folder to a Drive folder (it is created if it doesn't exist):

   ```
   cd "Desktop/7th sem"
   foldrive init
   ```

2. See what a sync would do — this touches nothing:

   ```
   foldrive status
   ```

3. Do it. The first sync shows its full plan and asks before transferring anything:

   ```
   foldrive sync
   ```

4. Optionally, let it run every 5 minutes in the background:

   ```
   foldrive autostart
   ```

### Usage Examples

| Command | What it does |
|---|---|
| `foldrive setup` | One-time Google setup; installs your OAuth client file |
| `foldrive login` / `logout` / `whoami` | Google account sign-in |
| `foldrive init` | Link the current folder to a Drive folder |
| `foldrive status` | Read-only preview of pending changes, both directions |
| `foldrive push` / `pull` / `sync` | Upload / download / both |
| `foldrive log` | What foldrive has done to this folder |
| `foldrive restore <path>` | Bring one file back from Drive |
| `foldrive ls <name>` | List a Drive folder's contents by name |
| `foldrive autostart` | Register background sync (`--remove`, `--status`) |

Flags: `--all` (list every file in `status`), `--yes` (never prompt),
`--allow-mass-delete` (see [Safety](#safety)), `-n N` (entries in `log`).

Checking what the background task did overnight:

```
$ foldrive log -n 4
  2026-08-12 03:15:04  downloaded                   Unit-3 Notes.pdf
  2026-08-12 03:15:02  uploaded                     lab/experiment-7.docx

  2026-08-11 22:40:11  moved to Recycle Bin         old-draft.docx
```

Recovering a file you deleted locally but kept in Drive:

```
$ foldrive restore "notes/unit-3.pdf"
restoring notes/unit-3.pdf
Restored to /home/me/college/notes/unit-3.pdf
```

### Test Instructions

```
pytest
```

Unit tests cover the diff engine — the pure logic that decides new / modified /
deleted / conflict on each side. For manual testing, use a throwaway folder and a
scratch Drive folder; foldrive moves real files.

## How it behaves

### Configuration

`foldrive init` writes `.googledrive.json` into the folder. Everything except the
Drive folder id is optional.

```json
{
  "drive_folder_id": "1ddlbDTp...",
  "drive_folder_name": "7th sem",
  "schedule": { "pull_every_minutes": 30, "push_every_minutes": 50 },
  "ignore": [".venv/", "__pycache__/", "node_modules/", "*.tmp", "~$*"],
  "conflict_policy": "ask",
  "conflict_overrides": { "notes/scratch.txt": "local" },
  "delete_policy": { "local": "trash", "drive": "trash" },
  "max_delete_percent": 25,
  "max_delete_minimum": 10,
  "google_native": { "docs": "download_only", "sheets": "skip", "slides": "download_only" }
}
```

Ignored by default: `.venv/`, `venv/`, `env/`, `__pycache__/`, `*.pyc`,
`node_modules/`, `.git/`, `build/`, `dist/`, `*.egg-info/`, `.idea/`, `.vscode/`,
`~$*`, `*.tmp`, `Thumbs.db`, `desktop.ini`, `.DS_Store`.

### Conflicts

A conflict is the same file changed on **both** sides since the last sync. Nothing
is lost: the newer version keeps the original name, the other is preserved beside
it as `notes (local copy).docx` or `notes (drive copy).docx`, and both end up on
both sides. Timestamps within 5 seconds count as a tie — then neither keeps the
name and both copies are written.

In a terminal foldrive asks once per conflict, *before* any transfer starts, so you
answer in the first few seconds and the rest runs unattended:

```
[k]eep both  [l]ocal wins  [d]rive wins  [s]kip
[K]/[L]/[D]/[S] to apply that to all remaining
```

Scheduled runs never prompt — they always keep both. Set
`"conflict_policy": "keep_both"` to skip prompting in manual runs, or pin
individual files with `conflict_overrides`.

### Deletions

Deleting on one side deletes on the other, **recoverably** — Recycle Bin locally,
Drive trash remotely. Set `delete_policy` per side, naming the side files are
deleted *from*:

```json
"delete_policy": { "local": "trash", "drive": "never_delete" }
```

That is the backup setup: local cleanup works normally, Drive keeps everything
forever. A plain string applies to both sides.

### Google Docs, Sheets and Slides

Native files have no bytes and no checksum, so they are handled separately, per type:

| Mode | Drive changes | Local changes | Both change |
|---|---|---|---|
| `skip` | ignored | ignored | ignored |
| `download_only` | download over the local file | not uploaded; `status` warns | local kept as a copy, then downloaded |
| `upload_only` | not downloaded; `status` warns | uploaded back into the same Doc | Drive version kept as a copy |
| `two_way` | download over the local file | uploaded back into the same Doc | usual conflict rules |

A Doc named `Notes` is the local file `Notes.docx`. Uploading writes back into the
**same** Drive document — same id, share links and version history, no duplicate.

Defaults are `docs: download_only`, `slides: download_only`, `sheets: skip`,
because `.xlsx` mangles cross-sheet formulas, charts and filter views, and `.docx`
loses comments and suggestion mode. Change detection uses Drive's modification
time, not a checksum, since exporting the same untouched document twice produces
different bytes.

### Safety

* **First sync never deletes.** Without a snapshot, "deleted" and "never synced"
  are indistinguishable, so foldrive assumes the safer one.
* **Mass-delete guard.** A run deleting at least `max_delete_minimum` files *and*
  at least `max_delete_percent` of a side is refused, since that usually means the
  other side wrongly looked empty. `--allow-mass-delete` overrides it — but the
  background task never can.
* **Partial reads stop the sync.** If a folder can't be read, foldrive says which
  one rather than mistaking missing files for deleted ones.
* **Interruptions are cheap.** Progress is checkpointed every 25 transfers, and
  re-running never duplicates: already-uploaded files come back as *identical*.
* **Offline is not an error.** Timestamps advance only on success, so an
  interrupted folder stays due and catches up on the next run.

### Background sync

```
foldrive autostart          # every 5 minutes
foldrive autostart --status
foldrive autostart --remove
```

| | How it registers |
|---|---|
| Windows | Task Scheduler job, no console window, keeps working on battery |
| macOS / Linux | a `crontab` line tagged `# foldrive-tick` |

`--remove` only touches foldrive's own entry; your other cron jobs are untouched.
Nothing prints to a terminal, so the rotating log is where you check on it —
`foldrive.log` in the app folder.

> **macOS one-time permission.** Any folder works, but `~/Desktop`, `~/Documents`
> and `~/Downloads` are protected by macOS, so you allow access once — the same
> grant Dropbox asks for. **System Settings → Privacy & Security → Full Disk
> Access → `+`**, then add your terminal app (for commands you run yourself) and
> `/usr/sbin/cron` (for background sync; press ⌘⇧G to type the hidden path).

### Platform support

| | Windows | macOS | Linux |
|---|---|---|---|
| Sync | ✅ | ✅ | ✅ |
| Background sync | ✅ Task Scheduler | ✅ cron | ✅ cron |

Config, token and logs live in each OS's standard location: `%APPDATA%\foldrive\`,
`~/Library/Application Support/foldrive/`, `~/.local/share/foldrive/`.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a history of changes, and the
[releases page](https://github.com/udbhav07/foldrive/releases) for versioned releases.

## Frequently Asked Questions (FAQ)

1. **I edited a file in the Drive web UI and foldrive ignored it. Why?**
   - Opening a `.txt` or `.docx` in Drive and editing it usually creates a
     *separate Google Doc* rather than changing the original file. Your original is
     untouched, and that's what foldrive keeps syncing. To really change a file in
     Drive, use *right-click → Manage versions → Upload new version*, or edit it
     locally and let foldrive push it.

2. **Why do I have to create my own Google OAuth client?**
   - A client id carries a shared quota and a 100-user cap for unverified apps.
     Your own client means your own uncontended quota and no dependency on anyone
     else's app staying healthy. It takes about five minutes, once.

3. **Is my data private? What does the client file give access to?**
   - `client_secret.json` identifies the *app* and grants access to nothing by
     itself. Signing in creates `token.json` beside it, which opens *your* Drive
     only. Revoke anytime at <https://myaccount.google.com/permissions>.

4. **Are my files encrypted in Drive?**
   - No — they are stored as ordinary Drive files, so they remain readable on
     drive.google.com and your phone. If you need Google to be unable to read
     them, encrypt the folder with a tool like Cryptomator and sync the encrypted
     folder with foldrive.

5. **Can two computers sync the same Drive folder?**
   - Yes. Each keeps its own snapshot and reconciles independently. Edit the same
     file on both before either syncs and you get the usual conflict copies.

6. **What happens if I delete a file by accident?**
   - Deletions are soft on both sides — Recycle Bin locally, Drive trash remotely.
     `foldrive restore <path>` brings a file back from Drive, and `foldrive log`
     shows what happened and when.

7. **Does it sync continuously, like Drive for Desktop?**
   - No. It runs on your schedule (default: pull every 30 minutes, push every 50),
     or whenever you type a command. That is the tradeoff for control and a small
     footprint.

## Contributing

1. Open an issue describing the change.
2. [Fork](https://github.com/udbhav07/foldrive/fork) the repo and work in your fork.
3. Run `pytest` and smoke-test against a **throwaway** sync folder — foldrive moves
   real files, and testing against real data is how people lose it.
4. Open a pull request describing what you changed and how you verified it.

Bug reports are most useful with the relevant lines from `foldrive log` and the
sync log, plus your `.googledrive.json` with the `drive_folder_id` removed.

## License

MIT — see [LICENSE](LICENSE).

## Support

Udbhav Sai — [@udbhav07](https://github.com/udbhav07) · <udbhavsai.k@gmail.com>

Questions and bugs: [GitHub issues](https://github.com/udbhav07/foldrive/issues).
