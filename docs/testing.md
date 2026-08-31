# Manual test checklist

Everything the automated suite cannot reach: the real OAuth flow, real Google
Docs, the actual Recycle Bin, and a scheduled task genuinely firing. None of it
can run in CI, so it runs here — by hand, once per release.

> **Use a throwaway local folder and a scratch Drive folder.** Several steps
> below delete files on purpose. Never point this at anything you care about.

Everything else is covered automatically:

```bash
pytest                                    # the whole suite
FOLDRIVE_FUZZ_TRIALS=1000 pytest -m slow  # the randomized suite, properly
```

## Setup

- [ ] A scratch Drive folder exists, containing a few files and one subfolder
- [ ] An empty local folder exists, with a name matching the Drive folder
- [ ] `foldrive --version` prints the expected version

## 1. First run

- [ ] `foldrive setup` with no argument prints the Google Cloud walkthrough
- [ ] `foldrive setup <client.json>` installs the client file
- [ ] `foldrive setup <client.json>` again refuses without `--force`
- [ ] `foldrive login` opens a browser and completes
- [ ] `foldrive whoami` shows the right account
- [ ] `foldrive init` finds the Drive folder by name and writes `.googledrive.json`
- [ ] `foldrive init` again refuses — already initialised
- [ ] `foldrive status` warns that the folder has never been synced
- [ ] `foldrive sync` prompts before the first sync, and `n` cancels it
- [ ] `foldrive sync` then `y` merges both sides
- [ ] **Nothing was deleted on either side** by that first sync
- [ ] `foldrive status` afterwards prints "Everything is in sync."
- [ ] A second `foldrive sync` transfers nothing

## 2. Ordinary changes

- [ ] Edit a file locally, `foldrive push` — Drive has the new content
- [ ] Edit a file in the Drive web UI, `foldrive pull` — the local file updates
- [ ] Add a nested local file (`a/b/c.txt`), push — the folders are created in Drive
- [ ] Rename a local file, sync — the old name goes, the new one arrives
- [ ] `foldrive status` from a *subdirectory* of the folder still works
- [ ] `foldrive status` outside any synced folder says so and exits

## 3. Conflicts

Use `python scripts/make_conflict.py shared.txt` to fabricate each one.

- [ ] `k` (keep both) — the newer side keeps the name, the other becomes
      `shared (local copy).txt` or `shared (drive copy).txt`, and **both files
      exist on both sides**
- [ ] `l` (local wins) — Drive takes the local content, no copies left behind
- [ ] `d` (Drive wins) — the local file takes Drive's content, no copies
- [ ] `s` (skip) — nothing changes on either side, and the conflict is still
      pending on the next `status`
- [ ] `K` answers every remaining conflict at once (make two conflicts first)
- [ ] A tie (edit both sides within a few seconds) gives the original name to
      neither — both become copies
- [ ] `"conflict_overrides": {"shared.txt": "local"}` in the config resolves it
      without prompting
- [ ] `--yes` never prompts and keeps both

## 4. Google Docs

Create a Doc, a Sheet and a Slides deck in the scratch Drive folder. Set
`google_native` in `.googledrive.json` for each pass.

- [ ] `"skip"` — nothing downloads, and `status` does not nag about them
- [ ] `"download_only"` — the Doc arrives as `.docx`; a **second sync does not
      download it again** (this is the byte-stability trap)
- [ ] `"download_only"` with a local edit — `status` notes the edit will never
      be uploaded, and `sync` does not upload it
- [ ] `"upload_only"` — a local `.docx` edit goes back into the *same* Doc:
      the Drive link, the file id and the revision history all survive
- [ ] `"two_way"` with edits on both sides — one side is kept as a copy and
      neither version is lost
- [ ] A Google Form or Drawing in the folder is skipped with a count, not an error
- [ ] Per-type modes work independently (Docs downloading while Sheets skip)

## 5. Deletions

- [ ] Delete a local file, push — the Drive copy is in **Drive's trash**, not
      gone permanently
- [ ] Delete a Drive file, pull — the local copy is in the **Recycle Bin**, not
      unlinked
- [ ] `"delete_policy": {"drive": "never_delete"}` — a local delete leaves the
      Drive copy alone, and `status` says so as a note rather than a pending change
- [ ] `"delete_policy": {"local": "never_delete"}` — the mirror case
- [ ] `"delete_policy": "never_delete"` as a bare string applies to both sides
- [ ] Delete a file locally *and* edit it in Drive — the edit wins, nothing is lost

## 6. The mass-delete guard

- [ ] Put 20+ files in the folder and sync
- [ ] Delete all of them locally, `foldrive push` — **refused**, with a message
      naming the count and the percentage
- [ ] Nothing was actually deleted in Drive
- [ ] `foldrive push --allow-mass-delete` goes through
- [ ] `"max_delete_percent": 0` disables the guard entirely
- [ ] Deleting 3 of 4 files in a small folder is **not** refused (under the
      minimum count)

## 7. Background sync

- [ ] `foldrive autostart` registers the task
- [ ] `foldrive autostart --status` shows it
- [ ] **Windows:** no console window flashes when a tick fires
- [ ] **Windows:** the task runs while on battery (unplug and wait through a tick)
- [ ] **macOS/Linux:** `crontab -l` shows exactly one foldrive line, and every
      pre-existing line of yours is still there
- [ ] Make a change, wait for a tick, and confirm it synced with nobody watching
- [ ] The log records what it did
- [ ] A tick with a conflict pending keeps both copies and does not hang waiting
      for input
- [ ] Go offline, wait through a tick — the log says "offline", nothing breaks
- [ ] Come back online — the next tick catches up on its own
- [ ] `foldrive autostart --remove` removes it, and on cron leaves your other
      lines untouched
- [ ] `foldrive autostart --remove` again says it was not enabled

## 8. Restore and log

- [ ] Delete a local file under `never_delete`, then `foldrive restore <path>`
      brings it back from Drive
- [ ] `foldrive restore` on a file that already exists locally refuses without
      `--force`
- [ ] `foldrive log` shows the actions from everything above, newest first
- [ ] `foldrive log -n 5` shows five
- [ ] `foldrive log --all` shows the lot

## 9. Interruptions and damage

- [ ] Start a sync with many files and press Ctrl-C mid-run — it exits with a
      message, not a traceback
- [ ] Re-run it: **no duplicates, no lost work**, and it does not start over
- [ ] Corrupt `.foldrive/state.json` — the next command explains how to recover
      rather than guessing
- [ ] Delete `.foldrive/` entirely and sync — it re-links both sides and
      deletes nothing
- [ ] Corrupt `.googledrive.json` — the error names the file and the problem
- [ ] `foldrive logout` then any command — "Not logged in. Run: foldrive login"

## 10. A clean install

On a machine, or a fresh virtualenv, that has never run foldrive:

- [ ] `pip install -e ".[dev]"` succeeds, and `pytest` is green
- [ ] `python -m build` produces a wheel and an sdist
- [ ] Installing that wheel puts `foldrive` on the PATH
- [ ] `foldrive --help` lists all fourteen commands
- [ ] `foldrive --version` matches `foldrive.__version__`
- [ ] `foldrive --version` works before `login` — no traceback about a missing
      token or a missing `%APPDATA%`
