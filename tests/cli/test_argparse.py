"""The argparse surface.

Catches the class of bug where a command is written under commands/ but never
wired into cli.py, or is wired to the wrong module — neither of which any other
test would notice, because every other test calls run() directly.

cli.main() builds its parser and dispatches in one go, so these drive it exactly
as the console script does: real argv, real parse, real dispatch, with each
command's run() replaced so nothing actually executes.
"""

import sys

import pytest

import foldrive
from foldrive import cli
from foldrive.commands import (
    autostart, init, log, login, logout, ls, pull, push, restore, setup, status,
    sync, tick, whoami,
)

# Every subcommand, and the module its run() must resolve to.
COMMANDS = {
    "setup": setup,
    "login": login,
    "whoami": whoami,
    "logout": logout,
    "ls": ls,
    "init": init,
    "status": status,
    "push": push,
    "pull": pull,
    "sync": sync,
    "log": log,
    "restore": restore,
    "tick": tick,
    "autostart": autostart,
}


@pytest.fixture
def run_cli(monkeypatch):
    """Call the CLI with argv, and report (module, args) it dispatched to."""
    def call(argv):
        dispatched = []
        for module in COMMANDS.values():
            monkeypatch.setattr(
                module, "run",
                lambda args, reached=module: dispatched.append((reached, args)),
            )
        monkeypatch.setattr(sys, "argv", ["foldrive", *argv])
        cli.main()
        assert len(dispatched) == 1, f"{argv} dispatched {len(dispatched)} times"
        return dispatched[0]

    return call


@pytest.fixture
def parse(run_cli):
    """Just the parsed args, for the argument-shape tests."""
    return lambda argv: run_cli(argv)[1]


# --- wiring ------------------------------------------------------------------

@pytest.mark.parametrize("name,module", sorted(COMMANDS.items(), key=lambda pair: pair[0]))
def test_every_command_parses_and_reaches_its_own_module(name, module, run_cli):
    reached, args = run_cli([name] if name != "restore" else [name, "a.pdf"])
    assert reached is module
    assert args.command == name


def test_there_are_fourteen_commands():
    """A count, so adding a command without wiring it up shows here rather than
    in a user's terminal."""
    assert len(COMMANDS) == 14


def test_no_two_commands_share_a_module(run_cli):
    """Two subcommands reaching the same run() would mean one silently does the
    other's job."""
    reached = [run_cli([name] if name != "restore" else [name, "a.pdf"])[0]
               for name in COMMANDS]
    assert len(set(reached)) == len(COMMANDS)


def test_a_missing_command_is_an_error(run_cli):
    with pytest.raises(SystemExit):
        run_cli([])


def test_an_unknown_command_is_an_error(run_cli):
    with pytest.raises(SystemExit):
        run_cli(["frobnicate"])


# --- per-command arguments ---------------------------------------------------

def test_status_all_defaults_off(parse):
    assert parse(["status"]).all is False


def test_status_accepts_all(parse):
    assert parse(["status", "--all"]).all is True


@pytest.mark.parametrize("name", ["push", "pull", "sync"])
def test_the_transfer_commands_take_yes_and_allow_mass_delete(name, parse):
    args = parse([name, "--yes", "--allow-mass-delete"])
    assert args.yes is True
    assert args.allow_mass_delete is True


@pytest.mark.parametrize("name", ["push", "pull", "sync"])
def test_the_transfer_commands_default_to_prompting(name, parse):
    args = parse([name])
    assert args.yes is False
    assert args.allow_mass_delete is False


def test_setup_takes_an_optional_path(parse):
    assert parse(["setup"]).path is None
    assert parse(["setup", "client.json"]).path == "client.json"
    assert parse(["setup", "--force"]).force is True


def test_ls_takes_an_optional_name(parse):
    assert parse(["ls"]).name is None
    assert parse(["ls", "7th sem"]).name == "7th sem"


def test_log_defaults_to_twenty_entries(parse):
    assert parse(["log"]).number == 20


def test_log_takes_a_count(parse):
    assert parse(["log", "-n", "5"]).number == 5
    assert parse(["log", "--number", "5"]).number == 5
    assert parse(["log", "--all"]).all is True


def test_log_rejects_a_non_numeric_count(run_cli):
    with pytest.raises(SystemExit):
        run_cli(["log", "-n", "lots"])


def test_restore_requires_a_path(run_cli, parse):
    with pytest.raises(SystemExit):
        run_cli(["restore"])
    assert parse(["restore", "notes/unit-3.pdf"]).path == "notes/unit-3.pdf"
    assert parse(["restore", "a.pdf", "--force"]).force is True


def test_autostart_takes_remove_and_status(parse):
    assert parse(["autostart"]).remove is False
    assert parse(["autostart", "--remove"]).remove is True
    assert parse(["autostart", "--status"]).status is True


# --- --version ---------------------------------------------------------------

def test_version_prints_the_package_version(run_cli, capsys):
    """Guards the single dynamic version source: pyproject reads this attribute,
    so the two can no longer disagree."""
    with pytest.raises(SystemExit) as stop:
        run_cli(["--version"])
    assert stop.value.code == 0
    assert capsys.readouterr().out.strip() == f"foldrive {foldrive.__version__}"


# --- Ctrl-C ------------------------------------------------------------------

def test_ctrl_c_is_a_message_not_a_traceback(monkeypatch):
    """Interrupting a long sync is a normal way to stop it. Each command saves
    its snapshot in a finally, so whatever finished is already recorded."""
    def interrupted(args):
        raise KeyboardInterrupt

    monkeypatch.setattr(status, "run", interrupted)
    monkeypatch.setattr(sys, "argv", ["foldrive", "status"])

    with pytest.raises(SystemExit, match="re-run to continue"):
        cli.main()
