"""is_overdue: the whole of offline recovery, in five lines.

Only a successful run writes a timestamp, so "overdue" is the default state and
a folder that failed retries by itself with no recovery code anywhere.
"""

from datetime import datetime, timedelta, timezone

from foldrive.scheduler import is_overdue


def minutes_ago(count):
    return (datetime.now(timezone.utc) - timedelta(minutes=count)).isoformat()


def test_never_synced_is_overdue():
    """A fresh folder has no timestamp at all - that is how it gets its first run."""
    assert is_overdue(None, 30) is True


def test_an_empty_string_is_overdue():
    assert is_overdue("", 30) is True


def test_unparseable_text_is_overdue():
    """A hand-edited state.json must retry, not crash the tick."""
    assert is_overdue("last tuesday", 30) is True


def test_a_fresh_timestamp_is_not_overdue():
    assert is_overdue(minutes_ago(1), 30) is False


def test_a_stale_timestamp_is_overdue():
    assert is_overdue(minutes_ago(45), 30) is True


def test_exactly_at_the_interval_is_overdue():
    assert is_overdue(minutes_ago(30), 30) is True


def test_just_inside_the_interval_is_not():
    assert is_overdue(minutes_ago(29), 30) is False


def test_a_future_timestamp_is_not_overdue():
    """Clock skew, or a machine that moved timezone: wait rather than resync."""
    ahead = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    assert is_overdue(ahead, 30) is False


def test_the_interval_is_respected_per_folder():
    stamp = minutes_ago(40)
    assert is_overdue(stamp, 30) is True      # pull, every 30
    assert is_overdue(stamp, 50) is False     # push, every 50
