# src/data_quality_toolkit/utils/logging.py
from __future__ import annotations

import json
import logging
import sys

from data_quality_toolkit.shared.settings import load_settings

__all__ = ["get_logger", "setup_logging"]


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class _PrefixFilter(logging.Filter):
    """Allow only loggers whose name starts with the given prefix."""

    def __init__(self, prefix: str):
        super().__init__()
        self.prefix = prefix

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self.prefix)


def setup_logging(level: str | None = None, fmt: str | None = None) -> None:
    """
    Initialize root logger.

    - text -> stdout (plain formatter)
    - json -> stderr (json formatter)
      + also mirror json to stdout for loggers starting with "dqt.test" (unit tests)
    """
    s = load_settings()
    chosen_level = (level or s.log_level or "INFO").upper()
    chosen_fmt = (fmt or s.log_format or "json").lower()

    root = logging.getLogger()
    logging.raiseExceptions = False

    # Clear existing handlers so reconfiguring in tests doesn't duplicate output
    handlers_snapshot = tuple(root.handlers)  # immutable snapshot for safe iteration
    for h in handlers_snapshot:
        root.removeHandler(h)

    if chosen_fmt == "text":
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    else:
        # Primary JSON handler -> stderr (keeps CLI stdout clean)
        err_handler = logging.StreamHandler(sys.stderr)
        err_handler.setFormatter(_JsonFormatter())
        root.addHandler(err_handler)

        # Test-only JSON mirror -> stdout (so unit tests can read from stdout)
        out_handler = logging.StreamHandler(sys.stdout)
        out_handler.setFormatter(_JsonFormatter())
        out_handler.addFilter(_PrefixFilter("dqt.test"))
        root.addHandler(out_handler)

    root.setLevel(getattr(logging, chosen_level, logging.INFO))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
