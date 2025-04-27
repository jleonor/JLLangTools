# utils/log_utils.py

import logging
from logging.handlers import TimedRotatingFileHandler

def setup_logger(name: str,
                 log_path: str,
                 level: int = logging.DEBUG) -> logging.Logger:
    """
    Returns a logger that logs to:
      • console at `level`
      • a midnight-rotating file at DEBUG
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        # File handler (DEBUG+)
        fh = TimedRotatingFileHandler(
            log_path, when='midnight', backupCount=7, encoding='utf-8'
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            fmt='%(asctime)s %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        logger.addHandler(fh)

        # Console handler (INFO+)
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(logging.Formatter(
            fmt='%(asctime)s %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        ))
        logger.addHandler(ch)

    logger.propagate = False
    return logger
