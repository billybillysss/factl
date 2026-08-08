from __future__ import annotations

import logging
import os

LOGGER_NAME = "factl"
DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _resolve_log_level(level: str | int | None = None) -> int:
    if isinstance(level, int):
        return level
    level_name = str(level or os.getenv("FACTL_LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()
    return getattr(logging, level_name, logging.INFO)


def configure_logging(level: str | int | None = None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_resolve_log_level(level))
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(handler)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    base_logger = configure_logging()
    if not name:
        return base_logger
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
