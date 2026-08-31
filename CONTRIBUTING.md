# Contributing to foldrive

foldrive moves people's files around and deletes things on their behalf. That
shapes everything below: the bar is not "does it work on your machine", it is
"can this lose someone's data".

## Getting set up

```bash
git clone https://github.com/udbhav07/foldrive
cd foldrive
python -m venv .venv
.venv/Scripts/activate        # Windows
source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
pytest
```

That is the whole setup. `pytest` needs no Google account and no network — the
suite runs against an in-memory `FakeDrive`.

## Running the tests

```bash
pytest                     # everything
pytest -m "not slow"       # skip the randomized suite (what CI runs on a PR)
pytest -m slow             # only the randomized suite
pytest tests/unit          # one layer
ruff check src tests scripts
```

The suite is in layers, and the directory says which one you are in:

| Directory | What it uses | What it is for |
|---|---|---|
| `tests/unit` | nothing — pure functions | the diff engine, the policies, the config |
| `tests/integration` | a `FakeDrive` | the executor and the commands end to end |
| `tests/cli` | argparse | that every command is wired up |
| `tests/platform` | a fake `subprocess.run` | cron and schtasks, testable from either OS |
| `tests/property` | randomized, `-m slow` | convergence, idempotency, no data loss |

The randomized suite takes a trial count from the environment. Raise it when you
have touched the engine or the executor:

```bash
FOLDRIVE_FUZZ_TRIALS=1000 pytest -m slow
```

## Where to put a change

`src/foldrive/engine.py` is pure — dicts in, `Action` objects out, no network
and no disk. `src/foldrive/executor.py` performs those actions and owns every
side effect. Keep that boundary: it is the reason the riskiest logic in the
project can be tested at all. If you find yourself wanting to call `drive.` or
open a file inside `engine.py`, the decision belongs in the engine and the doing
belongs in the executor.

[docs/architecture.md](docs/architecture.md) has the module map and the
classification truth table. [docs/design-decisions.md](docs/design-decisions.md)
explains the rules that look arbitrary until you know the bug behind them —
worth reading before you "simplify" one of them.

## The three areas that need more care

**Deletion.** Every deletion must land somewhere recoverable: Drive's trash or
the local Recycle Bin, never an unlink. If you change `apply_delete_policy`,
`mass_delete_check` or `DELETE_SIDE`, add tests to
`tests/unit/test_engine_policies.py` covering the boundary, not just the
happy path.

**Anything that reads one side of the sync.** The most expensive bug in this
project's history was a misindented `continue` that made every real file look
deleted, and the run reported success. If a code path can fail to read
something, it must raise rather than return an empty result — an empty result
is indistinguishable from "everything was deleted", and foldrive will act on it.

**The scheduler.** `tick` runs unattended: no console, no stdin, a different
working directory and a different `PATH`. It must never prompt, never block, and
never let one bad folder stop the others. Remember `SystemExit` is a
`BaseException` — `except Exception` does not catch it.

## Manual testing

Some things cannot be tested without a real Google account: the OAuth flow, real
Google Docs, the Recycle Bin, and a scheduled task actually firing.
[docs/testing.md](docs/testing.md) is the checklist. Run it against a throwaway
folder and a scratch Drive folder — never your own files.

`scripts/make_conflict.py` fabricates a real conflict against a live Drive
folder, which is otherwise fiddly to produce by hand.

## Pull requests

- One change per PR. A bug fix and a refactor in the same diff are hard to
  review and harder to revert.
- Keep the existing style. The code is consistent; match it rather than
  reformatting around your change.
- `ruff check` must be clean and `pytest -m "not slow"` must pass. CI runs both
  across Windows, macOS and Linux on Python 3.10 through 3.14.
- Say in the PR what you verified by hand, if anything.

If you are unsure whether something is in scope, open an issue first — a few
things (real-time sync, client-side encryption, full undo) are deliberate
non-goals rather than missing features.
