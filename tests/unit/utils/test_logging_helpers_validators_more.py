from __future__ import annotations

import json

from data_quality_toolkit.utils.logging import get_logger, setup_logging
from data_quality_toolkit.utils.validators import validate_pii


def test_json_logger_includes_exc_info(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    setup_logging()

    log = get_logger("dqt.test.exc")
    try:
        1 / 0
    except ZeroDivisionError:
        log.exception("boom")

    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["msg"] == "boom"
    # this line covers utils/logging.py exc_info branch
    assert "exc_info" in payload and "ZeroDivisionError" in payload["exc_info"]


def test_validate_pii_stub_always_false():
    assert validate_pii("any string with 123-45-6789") is False


def test_setup_logging_text_and_idempotent(monkeypatch):
    # first call: text
    setup_logging(level="INFO", fmt="text")
    logger = get_logger("x.y")
    logger.info("hello text")

    # second call should not duplicate handlers
    setup_logging(level="INFO", fmt="text")

    # Ensure logger is not None for type checker
    assert logger is not None

    # Check handlers either on this logger or its parent (depending on how your logging is configured)
    effective_handlers = logger.handlers or (logger.parent.handlers if logger.parent else [])
    assert len(effective_handlers) == 1
