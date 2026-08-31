# Security

foldrive holds an OAuth refresh token on disk that grants full access to the
signed-in user's Google Drive. That token, and anything that could expose it, is
the security surface of this project.

## Reporting a vulnerability

Report privately, not in a public issue:

- Open a [security advisory](https://github.com/udbhav07/foldrive/security/advisories/new), or
- email **udbhavsai.k@gmail.com**

Please include what an attacker gains, how to reproduce it, and the foldrive
version. You will get an acknowledgement within a few days. This is a
single-maintainer hobby project, so there is no formal SLA — but anything that
exposes a token or destroys data is treated as urgent.

Please do not test against anyone else's Drive account.

## Supported versions

The latest release. There are no backported security fixes for older versions;
upgrade instead.

## What foldrive stores, and where

| File | Contains | Location |
|---|---|---|
| `token.json` | the OAuth refresh + access token | the app data directory |
| `client_secret.json` | the OAuth client you installed | the app data directory |
| `folders.json` | absolute paths of your synced folders | the app data directory |
| `logs/foldrive.log` | activity, including file paths | the app data directory |
| `<folder>/.foldrive/state.json` | file names, sizes, md5s, Drive ids | inside each synced folder |
| `<folder>/.foldrive/history.jsonl` | what was done to each file, and when | inside each synced folder |

The app data directory is `%APPDATA%\foldrive` on Windows,
`~/Library/Application Support/foldrive` on macOS, and
`~/.local/share/foldrive` on Linux.

**`token.json` is a credential.** Anyone who can read it can read and write your
entire Drive until the grant is revoked. It is stored with whatever permissions
your OS gives a new file in your own profile directory — it is not separately
encrypted, and foldrive does not have a passphrase to encrypt it with.

Note that `.foldrive/state.json` and `.foldrive/history.jsonl` live *inside* the
synced folder and record your file names. They are in the default ignore list so
they are never uploaded, but if you share the folder by other means, they go
with it.

## Revoking access

`foldrive logout` deletes the local token. To revoke the grant itself — which is
what you want if a machine was lost or a token may have leaked — remove foldrive
at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
That invalidates the refresh token everywhere, not just on one machine.

## Design choices that affect security

- **No bundled OAuth client.** You install your own through `foldrive setup`, so
  no credential is shared between users and no one else's quota or 100-user cap
  applies to you.
- **No server.** foldrive has no backend and phones home to nothing. The only
  host it contacts is `googleapis.com`.
- **No client-side encryption.** Deliberate: encrypting file contents would
  break reading them from the Drive web and mobile apps, which is most of the
  point of syncing to Drive. If you need encrypted-at-rest cloud storage, use a
  tool built for that.
- **Everything runs as you.** There is no daemon, no service account and no
  elevation. The scheduled task runs under your own user.

## Out of scope

- Someone who already has code execution or read access to your user account.
  They can read `token.json`, and no design here prevents that.
- Google's own security. foldrive uses the standard installed-app OAuth flow.
- Files you deliberately place in a synced folder.
