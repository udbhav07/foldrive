import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(os.environ["APPDATA"])/"foldrive"/"logs"
LOG_PATH = LOG_DIR/"foldrive.log"

_configured = False

def get_logger():
    global _configured
    logger = logging.getLogger("foldrive")
    if not _configured:
        LOG_DIR.mkdir(parents=True,exist_ok=True)
        handler = RotatingFileHandler(LOG_PATH,maxBytes=1_000_000,backupCount=3,encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        _configured = True
    return logger