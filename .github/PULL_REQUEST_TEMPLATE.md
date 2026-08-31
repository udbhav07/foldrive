## What this changes

<!-- One or two sentences. What is different afterwards, and why. -->

## How it was verified

<!-- Which tests, and anything you ran by hand. -->

- [ ] `pytest -m "not slow"` passes
- [ ] `ruff check src tests scripts` is clean
- [ ] New behaviour has a test, or there is a reason here why it does not

## If this touches deletion, the scheduler, or the diff engine

These three are where a bug costs someone their files rather than their time.

- [ ] `pytest -m slow` run at least once locally
- [ ] The change cannot turn "I could not read this side" into "this side is empty"
- [ ] Deletions still go somewhere recoverable (Drive trash or the Recycle Bin)
