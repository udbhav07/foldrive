# Changelog

All notable changes to foldrive are recorded here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-08-12

First public release.

### Added
- `foldrive setup` — installs and validates the Google OAuth client file, so the
  one-time setup no longer ends with "save this into a hidden folder". Detects the
  common mistake of creating a Web application client instead of a Desktop one.
- `foldrive log` — per-folder history of every action foldrive took, grouped by run.
- `foldrive restore <path>` — bring a single file back from Drive, with suggestions
  for typos and partial names.
- Background sync on **macOS and Linux** via cron. `foldrive autostart` now works on
  all three platforms; `--remove` only ever touches foldrive's own crontab entry.
- Google Docs, Sheets and Slides support, configurable per type with four modes:
  `skip`, `download_only`, `upload_only`, `two_way`. A local edit uploads back into
  the *same* Doc, keeping its id, share links and version history.
- Per-side `delete_policy` (`local` / `drive`, each `trash` or `never_delete`),
  making Drive usable as a keep-everything backup.
- Mass-delete guard: a run that would delete a large share of a folder is refused
  unless `--allow-mass-delete` is passed. The background task can never override it.
- Progress output during transfers, and conflict sub-steps.
- Retries with exponential backoff on rate limits and server errors.

### Changed
- Config, token and logs now use each OS's standard location via `platformdirs`
  (Windows paths unchanged).
- Snapshot is saved every 25 transfers, so an interrupted sync loses little work.

### Fixed
- An unreadable folder is no longer treated as an empty one. `os.walk` silently
  skips directories it can't read, which made those files look deleted — foldrive
  would have trashed them in Drive. It now stops and names the folder.
- Timestamps are stored as ISO strings; previously a `datetime` object crashed the
  snapshot save at the end of a successful run.
- A crash before the sync loop is now logged instead of vanishing into a silent
  non-zero exit from the scheduler.
