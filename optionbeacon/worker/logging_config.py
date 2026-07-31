"""Worker logging handlers with Railway-compatible severity streams."""

from __future__ import annotations

import logging
import sys


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


class BelowWarningFilter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.WARNING


def worker_log_handlers(stdout=None, stderr=None):
    stdout_handler = logging.StreamHandler(stdout or sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(BelowWarningFilter())
    stderr_handler = logging.StreamHandler(stderr or sys.stderr)
    stderr_handler.setLevel(logging.WARNING)
    formatter = logging.Formatter(LOG_FORMAT)
    stdout_handler.setFormatter(formatter)
    stderr_handler.setFormatter(formatter)
    return stdout_handler, stderr_handler


def configure_worker_logging(*, force=False):
    logging.basicConfig(
        level=logging.INFO,
        handlers=list(worker_log_handlers()),
        force=force,
    )
