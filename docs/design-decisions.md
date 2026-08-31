# Design decisions

Why foldrive does things the way it does. Most of these look arbitrary until you
know the bug or the constraint behind them, and several were found the expensive
way — which is the reason they are written down rather than left in the code as
a comment somebody will eventually "clean up".

For *what* the pieces are, see [architecture.md](architecture.md).

---

## Things not to change without reading this first

### `roaming=True` in `paths.py`

`platformdirs` defaults to `LOCALAPPDATA` on Windows. foldrive passes
`roaming=True` to keep its data in `%APPDATA%`.

Dropping that flag silently relocates `token.json` and `folders.json` for every
existing install. Nothing errors: the user simply appears logged out, with no
folders registered, and their old data sits untouched in a directory nothing
reads any more. The same reasoning applies to `LOG_DIR`, which is deliberately
not `platformdirs`' `user_log_dir` — that would move logs to
`LOCALAPPDATA\foldrive\Logs`, away from where they already are.

### Google Doc exports are not byte-stable

The same untouched Google Doc exports to different bytes on every request. An
md5 comparison would therefore report "changed" forever and re-download the file
on every single run.

`modifiedTime` is the only usable change signal for native files. That is why
Docs, Sheets and Slides have their own action kinds throughout `engine.py`, why
their snapshot entries store `md5: None`, and why `classify` branches on
`is_google_native` before it compares hashes.

### `pythonw.exe` for the scheduled task

The Windows task runs `pythonw.exe -m foldrive.cli tick`, not the `foldrive`
console script. A console script belongs to the console subsystem, so Windows
allocates a terminal for it — a command prompt flashing on screen every five
minutes, forever.

The consequence is that under the scheduler `sys.stdout` is `None`. `print()`
handles that (CPython returns early); `sys.stdout.write()` raises
`AttributeError`. So `progress.py` uses `print()` only — a rule that cannot be
verified by running the tool by hand, because by hand there is always a stdout.

That is also why progress is one line per file with no `\r` progress bar: the
same output ends up in a log file at least as often as on a screen, and carriage
returns render there as garbage.

### Two thresholds in `mass_delete_check`

The guard trips only when a run would delete at least `max_delete_minimum`
files *and* at least `max_delete_percent` of that side.

Either test alone produces false positives constantly. A percentage on its own
trips on deleting 3 of 4 files in a small folder. A bare count on its own trips
on a routine cleanup of 20 files out of 4000. Both together only fire on the
shape of the actual bug being guarded against — one side coming back empty when
it should not have.

### `_read_crontab` must raise, not return `""`

cron has no append operation: the whole crontab is replaced on every write, so
`autostart` rewrites it from whatever `_read_crontab` returns.

`crontab -l` exits 1 with `no crontab for <user>` when none exists yet, which is
a normal first-run state and correctly returns `""`. Any *other* failure must
raise. Returning `""` there would mean mistaking an unreadable crontab for an
empty one — and then writing that back, deleting every cron job the user has.

Empty means empty only when something authoritative says so.

---

## The recurring bug

Three separate bugs, in three different subsystems, were the same mistake:
**confusing "I got nothing" with "I could not tell".**

| Where | What happened |
|---|---|
| `drive.list_tree` | a `continue` indented one level too far left returned only Google Docs, so every real file looked deleted — 12 local files were trashed, and the run logged `pull ok` |
| `scanner.scan` | `os.walk` skips unreadable directories by default; those files vanish from the results, which is indistinguishable from "they were deleted" |
| `autostart._read_crontab` | returned `""` on any failure, which would have wiped the user's cron jobs |

All three had the same fix: refuse to proceed when the data source could not
answer, instead of treating silence as an answer. `scan` now raises through
`on_walk_error`; `_read_crontab` raises on anything but "no crontab".

The first one is the one worth remembering: a one-character indentation error
became silent mass deletion **with a success message**. That is why the
mass-delete guard exists at all — it converts that entire class of bug into a
message instead of a data loss.

---

## Decisions worth defending

| Decision | Why |
|---|---|
| Snapshot-based three-way diff | Two-way cannot tell a create from a delete |
| `engine.py` is pure | The riskiest logic becomes unit-testable with no network |
| Conflicts answered up front | A long sync must not block on a question mid-run |
| Only success advances the timestamps | Offline recovery then needs no recovery code |
| Soft deletes everywhere | Every mistake stays recoverable |
| Per-side delete policy | "Drive is my backup, never delete from it" is a real, different use case |
| The scheduler cannot bypass a safety check | Unattended runs have nobody to sanity-check them |
| No bundled OAuth client | A shared client means a shared quota and a shared 100-user cap |
| cron before launchd/systemd | One implementation covers macOS and Linux; native ones are an upgrade, not a prerequisite |
| Checkpoint every 25 transfers | Low enough that a hard kill costs little rework, high enough that the write is free |

---

## Things learned the hard way

- **`except Exception` does not mean "catch everything".** `SystemExit` is a
  `BaseException`. One folder with a corrupt config was killing the tick for
  every remaining folder until `tick` started catching `(Exception, SystemExit)`.
- **Unattended is a different environment.** No console, no stdin, a different
  working directory, a different `PATH`, and an OS that may kill the process for
  reasons unrelated to the code. Nearly everything in `tick` and `autostart`
  exists because of one of those.
- **Background failures are invisible without a log.** A dropped `Path` import
  broke every command; `tick` failed silently for 13 minutes before anyone
  noticed. `tick`'s outermost `try/except` logs and re-raises for exactly this
  reason, and it logs its reason for doing *nothing* too.
- **`schtasks` defaults are wrong for a laptop.** `DisallowStartIfOnBatteries`
  defaults to true, so ticks stopped for three hours on battery with only
  `Last Result: -2147023829` to show for it (`0x8007042B`,
  `ERROR_PROCESS_ABORTED`). Those settings cannot be set from the schtasks
  command line, and registering from XML needs elevation — hence the PowerShell
  patch-up after creation, which is best-effort by design.
- **Fixing one bug reveals the next.** `is_overdue` was returning early while the
  timestamp it read was always `None`; neither bug was visible until the other
  was fixed. A clean run immediately after a fix proves very little.
- **Confirm the premise before debugging the code.** Two long debugging sessions
  went into correct code — once because the Wi-Fi was never actually off, once
  because the log lines being read were stale.

---

## Known limitations

These are accepted, not oversights:

- No real-time sync. Minutes, not seconds, by design.
- Google Docs round trips are lossy — comments, suggestions and cross-sheet
  formulas do not survive. Sheets default to `skip` for this reason.
- No full `undo`. Reversing an overwrite needs the previous content, which
  foldrive does not keep. Drive revisions could cover the remote side only.
- Case sensitivity differs by OS: a Drive folder holding both `Notes.txt` and
  `notes.txt` collapses to one file on Windows and macOS.
- Cloud placeholder files (OneDrive or iCloud "online-only") have no local bytes
  to hash.
- No client-side encryption. Deliberate — it would break access from the Drive
  web and mobile apps, which is most of the point of syncing to Drive.
