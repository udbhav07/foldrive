# foldrive

**Pair any local folder with any Google Drive folder.** Git-style two-way sync —
`push`, `pull`, `status` — plus per-folder scheduling and automatic catch-up
after being offline.

Google's own Drive for Desktop can't map an arbitrary local folder (say,
`Desktop\7th sem`) to an arbitrary My Drive folder (`My Drive/College/7th sem`)
— it only mirrors your whole Drive or backs folders up into a separate
"Computers" section. foldrive exists to fill exactly that gap, with git-like
explicit control. See [the full comparison](#how-is-this-different-from-google-drive-for-desktop)
below.

## Quick start

```
pip install foldrive          # (or: pip install -e . from a clone)
foldrive login                # one-time browser sign-in
cd "C:\...\7th sem"
foldrive init                 # links this folder to the Drive folder "7th sem"
foldrive sync                 # first sync shows the full plan, asks y/n
foldrive autostart            # optional: background sync on your schedule
```

Daily use: save files into the folder and forget about it (the scheduler
pushes/pulls on the intervals in `.googledrive.json`), or drive it manually:

```
foldrive status         # what's pending, both directions
foldrive status --all   # ...listing every file, not just the first 40
foldrive push           # upload local changes now
foldrive pull           # download Drive changes now
```

`status` is read-only — it never uploads, downloads, or writes state. It prints
a count per change type, then the first 40 affected files:

```
Folder : C:\Users\me\Desktop\6th sem
Drive  : 6th sem
Local  : 336 files    Drive: 163 files
This folder has never been synced — the first sync merges both sides.

  CONFLICT         -> both sides changed   24 file(s)
  ...
  CONFLICT         -> local is newer, keeps the name   CN/Short Notes.docx
  new in Drive     -> download   25 file(s)
  identical        -> just remember it   114 file(s)
  new locally      -> upload   198 file(s)

  new locally      -> upload   CN lab/1/client.cpp
  ...
  ... and 321 more (use --all to list every file)

361 change(s) pending. Run `foldrive sync` to apply.
```

*identical → just remember it* means the file is already the same on both
sides: foldrive transfers nothing and only records the pairing.

**Ignored by default:** foldrive skips things that are rebuildable or junk —
`.venv/`, `venv/`, `env/`, `__pycache__/`, `*.pyc`, `node_modules/`, `.git/`,
`build/`, `dist/`, `*.egg-info/`, `.idea/`, `.vscode/`, plus `~$*`, `*.tmp`,
`Thumbs.db`, `desktop.ini`, `.DS_Store`. Edit the `ignore` list in
`.googledrive.json` to change this per folder. (Existing folders keep the list
written at `init` time — edit the file to pick up new defaults.)

## How is this different from Google Drive for Desktop?

Drive for Desktop is excellent at what it does — real-time, battle-tested
two-way sync. If all you want is "my whole Drive, mirrored," use it. foldrive
exists because of the knobs it doesn't have:

| | Drive for Desktop | foldrive |
|---|---|---|
| Pair *any* local folder with *any* My Drive folder | ❌ | ✅ the core feature |
| Where synced folders land in Drive | whole-Drive mirror, or a separate **"Computers"** section | the real **My Drive** folder your phone and browser see |
| Local folder location | chosen by the app (inside its mirror) | wherever your folder already lives |
| Sync timing | always-on, real-time only | your schedule per folder (`pull every 30 min, push every 50 min`) — or fully manual |
| Manual control | none — it just acts | `push` / `pull` / `status`, git-style; first sync shows its full plan and asks before touching anything |
| Preview of pending changes | ❌ | `foldrive status` (`--all` for the full list) |
| Scriptable / CLI | ❌ | ✅ everything is a command |
| Config as a file | ❌ | `.googledrive.json` per folder, editable, versionable |
| Footprint | always-running background app | small Python CLI + a 5-minute scheduled task |
| Source | closed | open — a few hundred lines you can read |

**The dealbreaker scenario foldrive was built for:** you keep `Desktop\7th sem`
locally and `My Drive/College/7th sem` in the cloud. Drive for Desktop can't
connect those two — backing up the local folder puts it in "Computers → My
Laptop", a *separate tree* from My Drive, so a PDF you save to the My Drive
folder from your phone never reaches your laptop. foldrive pairs the two
folders directly, both directions.

What Drive for Desktop does better, honestly: instant real-time propagation
(foldrive's scheduler works in minutes, not seconds), years of hardening, and
zero setup for the whole-Drive-mirror case. foldrive trades that for control,
transparency, and folder pairing.

## One-time Google setup (app owner only)

If you installed a build that bundles a `client_secret.json`, skip this — just
run `foldrive login`. (You'll see Google's "unverified app" warning once; click
**Advanced → Go to foldrive → Allow**. That's expected for small personal
tools; verification is a paid audit meant for commercial apps.)

To use your own (free) Google OAuth app instead:

1. Go to <https://console.cloud.google.com> → create a project (any name).
2. **APIs & Services → Library** → search *Google Drive API* → **Enable**.
3. **APIs & Services → OAuth consent screen** → User type **External** → fill
   in an app name and your email → save → **Publish app** ("In production").
   *Don't skip publishing: in "Testing" status Google expires your login every
   7 days.*
4. **APIs & Services → Credentials → Create credentials → OAuth client ID** →
   Application type **Desktop app** → **Download JSON**.
5. Save the file as `%APPDATA%\foldrive\client_secret.json`.
6. `foldrive login`.

Privacy model: `client_secret.json` identifies the *app* and grants access to
nothing. Your login creates `%APPDATA%\foldrive\token.json`, which opens *your*
Drive only — different users of the same app can never see each other's files.
Revoke anytime at <https://myaccount.google.com/permissions>.

## Notes

- Deletions are always soft: Drive trash on the remote side, Recycle Bin
  locally. Nothing foldrive does is unrecoverable.
- Conflicts (same file differs on both sides) never lose data. The newer
  version keeps the original name; the other is preserved beside it as
  `notes (local copy).docx` or `notes (drive copy).docx` — the label says which
  side that version came from. Both files end up on **both** sides; you keep
  the one you want and delete the other.
  - Timestamps within 5 seconds of each other count as a tie (the two clocks
    aren't the same) — then there's no winner and both copies are kept.
  - Run it in a terminal and foldrive asks per conflict:
    `[k]eep both / [l]ocal wins / [d]rive wins / [s]kip / [K]eep both for all`.
    Scheduled runs never ask — they always keep both.
  - Set `"conflict_policy": "keep_both"` in `.googledrive.json` to skip the
    prompts in manual runs too (`"ask"` is the default).

### What resolving one conflict does

Say `notes.docx` differs on both sides and the local copy is newer
(`winner = local`). foldrive:

1. Downloads Drive's version and saves it locally as `notes (drive copy).docx`
2. Uploads that same file back to Drive as `notes (drive copy).docx`
3. Uploads the local `notes.docx`, overwriting Drive's copy — the winner keeps
   the original name
4. Records both files in the snapshot, so the next run sees them as settled

When Drive's copy is newer the steps mirror: the local file is renamed to
`notes (local copy).docx` and uploaded, Drive's version is downloaded over
`notes.docx`. On a tie neither keeps the name — both `(local copy)` and
`(drive copy)` are written to both sides.

Either way both sides end up identical, with every version still present.

Note that `notes.docx` here means a **real Word file** — one that was uploaded
to Drive as a `.docx`. A Google Doc is a different thing entirely; see below.

### Google Docs, Sheets and Slides

Google-native files are **currently skipped**, and `status` reports how many.
They aren't files in the normal sense: they have no bytes to download and no
checksum, so nothing to compare or transfer.

This surprises people, so worth stating plainly: **opening a `.txt` or `.docx`
in the Drive web UI and editing it usually creates a separate Google Doc**
rather than changing the original file. Your original stays untouched, and
foldrive keeps syncing that — while the new Doc is skipped. To genuinely change
a file's contents in Drive, use *right-click → Manage versions → Upload new
version*, or just edit it locally and let foldrive push it.

Planned support, configurable per type in `.googledrive.json`:

```json
"google_native": {
  "document":     { "mode": "download_only", "format": "docx" },
  "presentation": { "mode": "download_only", "format": "pptx" },
  "spreadsheet":  { "mode": "skip",          "format": "xlsx" }
}
```

| Mode | Drive changes | Local changes | Both change |
|---|---|---|---|
| `skip` | ignored | ignored | ignored |
| `download_only` | re-export over the local file | not pushed; `status` warns | local file kept as `Notes (local copy).docx`, then re-exported |
| `upload_only` | not pulled; `status` warns | converted back into the same Doc | Drive version kept as a copy, then local uploaded |
| `two_way` | re-export over the local file | converted back into the same Doc | usual conflict rules |

`download_only` is what **rclone** does — its Drive backend exports natives to a
chosen format and can't upload them back, so bisync handles Docs one-way only.
`upload_only` and `two_way` have no rclone equivalent: writing a local edit back
into the *same* Drive document is what foldrive adds on top.

There's still just **one file on each side**: Drive's `Notes` and your local
`Notes.docx` are the same document. `two_way` syncs it like any other file —
edits in Drive refresh the local copy, local edits convert back into the *same*
Doc (same id, same share links, same version history, no duplicate file) — and
if both sides changed you get `Notes (drive copy).docx` as usual.

**Nothing is silently destroyed in any mode.** Even under `download_only`, a
locally-edited file is renamed to `Notes (local copy).docx` before the fresh
export lands, so an accidental local edit can't vanish.

**Why `two_way` is lossy:** a Google Doc holds things `.docx` can't represent
(comments, suggestion mode, some formatting), and a Sheet holds cross-sheet
formulas, charts and filters that `.xlsx` mangles. Pushing a locally-edited copy
rebuilds the Drive document from the converted file, so those extras are lost.
That's why Docs and Slides default to `download_only` and Sheets to `skip`.

Change detection for native files uses Drive's modified time rather than a
checksum, since exporting the same document twice doesn't produce identical
bytes.

- Folders inside OneDrive work, but two sync agents over one tree can be
  noisy; a sync root outside OneDrive is calmer.

## Status

Under active development.

Working today: `login`, `whoami`, `logout`, `ls`, `init`, `status`
(`--all`) — foldrive can link a folder pair and tell you exactly what a sync
would do, in both directions, including conflicts.

Coming next: `push` (uploads), then `pull`/`sync` with conflict copies, then
the scheduler (`tick`/`autostart`), then packaging.
