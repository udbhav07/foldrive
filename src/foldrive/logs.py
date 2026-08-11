import logging
from logging.handlers import RotatingFileHandler
from .paths import LOG_DIR,LOG_PATH

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