from __future__ import annotations

import json
import logging

from data_quality_toolkit.utils.helpers import ensure_dir, make_column_id, stable_seed
from data_quality_toolkit.utils.logging import get_logger, setup_logging
from data_quality_toolkit.utils.validators import validate_csv_path


def test_stable_seed_is_deterministic():
    a = stable_seed("sha1:abc", "profile")
    b = stable_seed("sha1:abc", "profile")
    c = stable_seed("sha1:abc", "other")
    assert a == b
    assert a != c
    assert 0 <= a <= 0xFFFFFFFF


def test_ensure_dir(tmp_path):
    p = tmp_path / "nested" / "dir"
    out = ensure_dir(p)
    assert out.exists() and out.is_dir()
    assert out == p


def test_make_column_id():
    cid = make_column_id("sha1:abc", "age")
    assert cid == "sha1:abc:age"


def test_validate_csv_path(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    assert validate_csv_path(str(f)) is True
    assert validate_csv_path(str(tmp_path / "nope.csv")) is False
    assert validate_csv_path(str(tmp_path / "x.txt")) is False


def test_setup_logging_text_format(monkeypatch, capsys):
    # Force text
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    setup_logging()
    logger = get_logger("dqt.test")
    logger.info("hello")
    out = capsys.readouterr().out
    assert "hello" in out
    assert "dqt.test" in out
    assert "INFO" in out


def test_setup_logging_json_format(monkeypatch, capsys):
    # Force json
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    setup_logging()
    logger = get_logger("dqt.test.json")
    logger.warning("hey")
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["msg"] == "hey"
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "dqt.test.json"


def test_get_logger_idempotent_handlers(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "text")
    setup_logging()
    a = get_logger("dqt.same")
    pre = len(a.handlers)
    setup_logging()  # calling again shouldn’t add handlers
    post = len(a.handlers)
    assert pre == post
    assert a.level in (
        logging.NOTSET,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.DEBUG,
        logging.CRITICAL,
    )
    assert a.level in (
        logging.NOTSET,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.DEBUG,
        logging.CRITICAL,
    )
