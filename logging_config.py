import logging
import os


def setup_logging():
    level_name = os.getenv("CHEFSYNC_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger("chefsync-agent")
    if not logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(message)s",
        )
    logger.setLevel(level)
    return logger
