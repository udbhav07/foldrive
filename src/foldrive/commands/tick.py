"""Runs whatever is due. Never prompts, never blocks — a scheduled task runs this."""

import os
from argparse import Namespace
from googleapiclient.errors import HttpError
from .. import auth,config,logs,scheduler,state
from . import pull,push

def run(args):
    """Outermost guard. Nothing here may fail silently: this runs unattended, so an
    unlogged crash means the user's folders quietly stop syncing with no clue why -
    Task Scheduler records only "Last Result: 1", which nobody is watching."""
    logger = logs.get_logger()
    try:
        _run_all(logger)
    except (Exception, SystemExit) as failure:
        logger.exception(f"tick aborted: {failure}")
        raise


def _run_all(logger):
    if not scheduler.is_online():
        logger.info("offline-nothing attempted")
        return

    if auth.get_credentials() is None:
        #Permanent until a human acts; say it once, not once per folder.
        logger.error("not logged in - run: foldrive login")
        return

    folders = config.registered_folders()
    if not folders:
        logger.info("no registered folders")
        return

    for folder in folders:
        try:
            _tick_one_folder(folder, logger)
        except (Exception, SystemExit) as failure:
            # SystemExit is a BaseException, so a bare `except Exception` would let
            # one corrupt config file kill the tick for every remaining folder.
            logger.exception(f"[{folder.name}] unexpected failure: {failure}")


def _tick_one_folder(folder, logger):
    folder_config = config.load_config(folder)
    current_state = state.load_state(folder)
    schedule = folder_config["schedule"]

    pull_due = scheduler.is_overdue(current_state.get("last_pull_ok"),
                                    schedule["pull_every_minutes"])
    push_due = scheduler.is_overdue(current_state.get("last_push_ok"),
                                    schedule["push_every_minutes"])

    if not pull_due and not push_due:
        return

    if not current_state["files"]:
        # A first sync merges two unknown trees; a human should watch that happen.
        logger.warning(f"[{folder.name}] never synced - run `foldrive sync` once by hand")
        return

    # yes=True: no prompts. Conflicts fall back to keeping both copies.
    quiet_args = Namespace(yes=True, all=False)
    original_directory = os.getcwd()
    try:
        os.chdir(folder)
        if pull_due:
            _run_half(pull.run, quiet_args, folder, "pull", logger)
        if push_due:
            _run_half(push.run, quiet_args, folder, "push", logger)
    finally:
        os.chdir(original_directory)

def _run_half(command_function, quiet_args, folder, label, logger):
    try:
        command_function(quiet_args)
        logger.info(f"[{folder.name}] {label} ok")
    except HttpError as api_error:
        status = api_error.resp.status
        if status in (403, 429) or status >= 500:
            # Transient: the timestamp stays stale, so the next tick retries.
            logger.warning(f"[{folder.name}] {label} rate-limited/server error ({status}) - will retry")
        elif status == 404:
            logger.error(f"[{folder.name}] {label} failed: Drive folder is gone - re-run `foldrive init`")
        else:
            logger.error(f"[{folder.name}] {label} failed: {status} {api_error.reason}")
    except OSError:
        logger.warning(f"[{folder.name}] {label} lost the network — will retry")
    except SystemExit as stop:
        logger.error(f"[{folder.name}] {label} stopped: {stop}")  