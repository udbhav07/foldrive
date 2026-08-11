"""Per-file progress lines for long transfers.

print() only, never sys.stdout.write(): the scheduled task runs pythonw.exe, where
sys.stdout is None. print() handles that (CPython returns early); a direct .write()
would raise AttributeError only under the scheduler and never when tested by hand.

No carriage-return progress bar for the same reason - these lines end up in a log
file as often as on a screen, and \r renders as garbage there. One line per unit of
work reads correctly in both places.
"""

MAX_NAME_WIDTH = 60
DETAIL_INDENT = " " * 8

# Kinds that move bytes and take real time. "link" and "forget" only touch the
# snapshot in memory, so counting them would inflate the total and make the
# numbers lie about how much work is left.
TRANSFER_KINDS = {
    "upload_new", "upload_changed",
    "download_new", "download_changed",
    "trash_remote", "recycle_local",
}

VERBS = {
    "upload_new": "uploading",
    "upload_changed": "updating on Drive",
    "download_new": "downloading",
    "download_changed": "updating locally",
    "trash_remote": "trashing on Drive",
    "recycle_local": "recycling locally",
}

CONFLICT_LABELS = {
    "keep_both": "keeping both:",
    "local": "local wins:",
    "drive": "Drive wins:",
}


def _shorten(name):
    """Keep the tail: the filename matters more than the leading directories."""
    if len(name) <= MAX_NAME_WIDTH:
        return name
    return "..." + name[-(MAX_NAME_WIDTH - 3):]


class Reporter:
    """Numbers each unit of work as it starts, with optional sub-steps beneath it."""

    def __init__(self, total):
        self.total = total
        self.completed = 0
        self._counter_width = len(str(total)) if total else 1

    @classmethod
    def for_actions(cls, actions):
        return cls(sum(1 for action in actions if action.kind in TRANSFER_KINDS))

    @classmethod
    def for_conflicts(cls, choices):
        return cls(sum(1 for _, choice in choices if choice != "skip"))

    def item(self, label, name):
        """Print before the work, not after: if a file hangs, its name is the last
        thing on screen, which is exactly what you need to know."""
        self.completed += 1
        print(f"  [{self.completed:>{self._counter_width}}/{self.total}] "
              f"{label} {_shorten(name)}")

    def detail(self, text):
        """A sub-step of the current item - one conflict can be three transfers."""
        print(f"{DETAIL_INDENT}-> {text}")

    def starting(self, action):
        if action.kind not in TRANSFER_KINDS:
            return
        self.item(VERBS.get(action.kind, action.kind), action.relpath)


class SilentReporter(Reporter):
    """For callers that don't want output. Saves every call site an `if reporter:`."""

    def __init__(self):
        super().__init__(0)

    def item(self, label, name):
        pass

    def detail(self, text):
        pass

    def starting(self, action):
        pass


SILENT = SilentReporter()
