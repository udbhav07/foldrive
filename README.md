# foldrive

**Pair any local folder with any Google Drive folder.** Git-style two-way sync —
`status`, `push`, `pull` — plus per-folder scheduling and automatic catch-up after
being offline.

Google's own Drive for Desktop can't map an arbitrary local folder (say
`Desktop\7th sem`) to an arbitrary My Drive folder (`My Drive/College/7th sem`).
foldrive exists to fill exactly that gap.

```
foldrive login                 # one-time browser sign-in
cd "Desktop/7th sem"
foldrive init                  # link this folder to the Drive folder "7th sem"
foldrive status                # see exactly what a sync would do
foldrive sync                  # do it
foldrive autostart             # optional: keep it synced every 5 minutes
```

---

## Commands

| Command | What it does |
|---|---|
| `foldrive login` / `logout` / `whoami` | Google account sign-in |
| `foldrive init` | Link the current folder to a Drive folder (creates it if absent) |
| `foldrive status` | Read-only preview of every pending change, both directions |
| `foldrive push` | Upload local changes |
| `foldrive pull` | Download Drive changes |
| `foldrive sync` | Pull, then push |
| `foldrive ls <name>` | List a Drive folder's contents by name |
| `foldrive tick` | Run whatever is due (what the background task calls) |
| `foldrive autostart` | Register/remove the background task (`--remove`, `--status`) |

Useful flags: `--all` (list every file in `status`), `--yes` (never prompt),
`--allow-mass-delete` (see [Safety](#safety)).

`status` never writes anything. It prints a count per change type, then the files:

```
Folder : C:\Users\me\Desktop\6th sem
Drive  : 6th sem
Local  : 336 files    Drive: 163 files

  CONFLICT         -> both sides changed        24 file(s)
  new in Drive     -> download                  25 file(s)
  new locally      -> upload                   198 file(s)
  identical        -> just remember it         114 file(s)

  new locally      -> upload   CN lab/1/client.cpp
  ... and 321 more (use --all to list every file)

361 change(s) pending. Run `foldrive sync` to apply.
```

*identical → just remember it* means the file already matches on both sides:
nothing transfers, foldrive only records the pairing.

---

## Why not Drive for Desktop?

If you want "my whole Drive, mirrored", use Drive for Desktop — it's real-time and
battle-tested. foldrive exists for the knobs it doesn't have:

| | Drive for Desktop | foldrive |
|---|---|---|
| Pair *any* local folder with *any* Drive folder | ❌ | ✅ the core feature |
| Where folders land in Drive | whole-Drive mirror, or a separate **"Computers"** section | the real **My Drive** folder your phone sees |
| Sync timing | always-on, real-time | your schedule per folder, or fully manual |
| Preview before it acts | ❌ | `foldrive status` |
| Scriptable | ❌ | ✅ everything is a command |
| Config | ❌ | `.googledrive.json` per folder |
| Footprint | always-running app | a 5-minute scheduled task |

**The scenario it was built for:** you keep `Desktop\7th sem` locally and
`My Drive/College/7th sem` in the cloud. Drive for Desktop can't connect those —
backing up the local folder puts it under "Computers → My Laptop", a *separate
tree*, so a PDF you save from your phone never reaches your laptop.

Honestly, what Drive for Desktop does better: instant propagation (foldrive works
in minutes), years of hardening, and zero setup for the mirror case.

---

## Configuration

`foldrive init` writes `.googledrive.json` into the folder. Everything is optional
except the Drive folder id.

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

**Ignored by default:** rebuildable or junk files — `.venv/`, `venv/`, `env/`,
`__pycache__/`, `*.pyc`, `node_modules/`, `.git/`, `build/`, `dist/`, `*.egg-info/`,
`.idea/`, `.vscode/`, `~$*`, `*.tmp`, `Thumbs.db`, `desktop.ini`, `.DS_Store`.
Existing folders keep the list written at `init` time.

---

## Conflicts

A conflict is the same file changed on **both** sides since the last sync. Nothing
is ever lost: the newer version keeps the original name, the other is preserved
beside it as `notes (local copy).docx` or `notes (drive copy).docx`. Both files end
up on both sides — keep the one you want, delete the other.

Timestamps within **5 seconds** count as a tie (the two clocks aren't the same);
then neither keeps the name and both copies are written.

In a terminal, foldrive asks once per conflict — and asks *before* any transfer
starts, so you answer in the first few seconds and the rest runs unattended:

```
[k]eep both  [l]ocal wins  [d]rive wins  [s]kip
[K]/[L]/[D]/[S] to apply that to all remaining
```

Scheduled runs never prompt; they always keep both. Set
`"conflict_policy": "keep_both"` to skip prompting in manual runs too, or pin
individual files with `conflict_overrides`.

---

## Deletions

Deleting a file on one side deletes it on the other **recoverably** — Recycle Bin
locally, Drive trash remotely. Nothing foldrive does is unrecoverable.

Set `delete_policy` per side, naming the side files are deleted **from**:

```json
"delete_policy": { "local": "trash", "drive": "never_delete" }
```

That's the backup setup: local cleanup works normally, but **Drive keeps
everything forever**. `status` reports what's being kept as a footnote.

A shorthand string applies to both sides: `"delete_policy": "never_delete"`.

---

## Google Docs, Sheets and Slides

Google-native files have no bytes and no checksum, so they're handled separately —
configurable per type:

| Mode | Drive changes | Local changes | Both change |
|---|---|---|---|
| `skip` | ignored | ignored | ignored |
| `download_only` | download over the local file | not uploaded; `status` warns | local kept as a copy, then downloaded |
| `upload_only` | not downloaded; `status` warns | uploaded back into the same Doc | Drive version kept as a copy |
| `two_way` | download over the local file | uploaded back into the same Doc | usual conflict rules |

A Doc named `Notes` is the local file `Notes.docx`. Uploading writes back into the
**same** Drive document — same id, same share links, same version history, no
duplicate. There's one file per side, never a shadow copy.

**Defaults are `docs: download_only`, `slides: download_only`, `sheets: skip`,**
because `.xlsx` mangles cross-sheet formulas, charts and filter views — a round
trip can quietly break a working spreadsheet. `.docx` loses comments and
suggestion mode. Nothing is destroyed silently in any mode: the losing side is
always preserved as a copy first.

There is no "upload a new local `.docx` as a Doc" — Docs are born in Drive;
foldrive carries edits back into one that already exists.

Change detection uses Drive's modification time, not a checksum, because exporting
the same untouched document twice produces different bytes.

> **A common surprise:** opening a `.txt` or `.docx` in the Drive web UI and
> editing it usually creates a *separate* Google Doc rather than changing the
> original. To really change a file in Drive, use *right-click → Manage versions →
> Upload new version*, or edit it locally and let foldrive push it.

---

## Safety

- **First sync never deletes.** With no snapshot, "deleted" and "never synced" are
  indistinguishable, so foldrive assumes the safer one and keeps both sides.
- **Mass-delete guard.** A run that would delete at least `max_delete_minimum`
  files *and* at least `max_delete_percent` of a side is refused:

  ```
  Refusing to continue: this would move 384 of 384 local files (100%) to the Recycle Bin.
  That usually means the other side looked empty when it should not have.
  ```

  Override with `--allow-mass-delete`. **The background task can never override
  it** — the escape hatch is unavailable to unattended runs by design.
- **Interruptions are cheap.** Progress is saved every 25 transfers, so Ctrl-C or a
  crash costs at most a few files of re-work. Re-running never creates duplicates:
  files already uploaded come back as *identical → just remember it*.
- **Offline is not an error.** Timestamps only advance on success, so a folder that
  couldn't sync stays due and catches up on the next run.

---

## Background sync

```
foldrive autostart            # every 5 minutes
foldrive autostart --status
foldrive autostart --remove
```

On Windows this registers a Task Scheduler job that runs without a console window
and **keeps working on battery**. Logs go to the app folder (`foldrive.log`,
rotated at 1 MB).

On macOS and Linux, `autostart` isn't implemented yet — use cron, which calls the
same command:

```
*/5 * * * * foldrive tick
```

---

## Install

Not on PyPI yet — install from a clone:

```
git clone <this repo> && cd foldrive
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -e .
```

Then the one-time Google setup, unless you installed a build with a bundled
`client_secret.json` (in which case just run `foldrive login` and accept the
"unverified app" warning once — **Advanced → Go to foldrive → Allow**).

<details>
<summary>Using your own free Google OAuth app</summary>

1. <https://console.cloud.google.com> → create a project.
2. **APIs & Services → Library** → *Google Drive API* → **Enable**.
3. **OAuth consent screen** → User type **External** → app name + your email →
   **Publish app**. *Don't skip publishing: in "Testing" status Google expires
   your login every 7 days.*
4. **Credentials → Create credentials → OAuth client ID** → **Desktop app** →
   **Download JSON**.
5. Save it as `client_secret.json` in foldrive's app folder:

   | | |
   |---|---|
   | Windows | `%APPDATA%\foldrive\` |
   | macOS | `~/Library/Application Support/foldrive/` |
   | Linux | `~/.local/share/foldrive/` |

6. `foldrive login`.

`client_secret.json` identifies the *app* and grants access to nothing. Your login
creates `token.json` beside it, which opens *your* Drive only. Revoke anytime at
<https://myaccount.google.com/permissions>.
</details>

---

## Platform support

| | Windows | macOS | Linux |
|---|---|---|---|
| Sync (`init`, `status`, `push`, `pull`, `sync`) | ✅ | ✅ | ✅ |
| Background sync (`autostart`) | ✅ | cron | cron |

## Notes

- Folders inside OneDrive work, but two sync agents over one tree can be noisy; a
  sync root outside OneDrive is calmer.
- Drive allows two files with the same name in one folder; foldrive matches by
  path and won't create duplicates on re-runs.

---


## Contributing

Issues and pull requests are welcome. Before opening a PR:

```
pytest                     # unit tests for the diff engine
foldrive status            # smoke-test against a scratch folder, not real data
```

Please use a throwaway sync folder for manual testing — the whole point of this
tool is that it moves real files around.

## License

MIT — see [LICENSE](LICENSE).

## Contact

Udbhav Sai — <udbhavsai.k@gmail.com>

