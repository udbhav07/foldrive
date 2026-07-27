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
foldrive status     # what's pending, both directions
foldrive push       # upload local changes now
foldrive pull       # download Drive changes now
```

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
| Preview of pending changes | ❌ | `foldrive status` |
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
- Conflicts (same file edited on both sides): newest wins, the other version
  is kept alongside as `name (conflict YYYY-MM-DD).ext`.
- Google-native files (Docs/Sheets/Slides) are skipped with a notice — they
  have no binary content to sync.
- Folders inside OneDrive work, but two sync agents over one tree can be
  noisy; a sync root outside OneDrive is calmer.

## Status

Under active development. Working today: `login`, `whoami`. Coming next:
`init`/`status`/`push` (one-way MVP), then `pull`/`sync`, then the scheduler
(`tick`/`autostart`).
