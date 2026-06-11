"""Unit tests for shared/error_contract.py — to_error_info."""

from __future__ import annotations

from data_quality_toolkit.shared.error_contract import to_error_info
from data_quality_toolkit.shared.exceptions import AssessmentError, ConfigError, DQTError
from data_quality_toolkit.shared.models import ErrorInfo

# ── DQTError ──────────────────────────────────────────────────────────────────


def test_dqt_error_basic() -> None:
    info = to_error_info(DQTError("boom"))
    assert info["code"] == "DQTERROR"
    assert info["message"] == "boom"
    assert info["exc_type"] == "DQTError"


def test_dqt_error_subclass_code() -> None:
    info = to_error_info(ConfigError("bad config"))
    assert info["code"] == "CONFIGERROR"
    assert info["exc_type"] == "ConfigError"
    assert info["message"] == "bad config"


def test_dqt_error_assessment_subclass() -> None:
    info = to_error_info(AssessmentError("score failed"))
    assert info["code"] == "ASSESSMENTERROR"
    assert "score failed" in info["message"]


def test_dqt_error_with_hint() -> None:
    exc = DQTError("oops", hint="check your config")
    info = to_error_info(exc)
    assert info.get("hint") == "check your config"


def test_dqt_error_with_metadata() -> None:
    exc = DQTError("oops", metadata={"field": "age", "value": -1})
    info = to_error_info(exc)
    assert info.get("metadata") == {"field": "age", "value": -1}


def test_dqt_error_no_hint_no_metadata() -> None:
    info = to_error_info(DQTError("bare"))
    assert "hint" not in info or info.get("hint") is None
    assert "metadata" not in info or info.get("metadata") is None


# ── FileNotFoundError ─────────────────────────────────────────────────────────


def test_file_not_found_code_and_message() -> None:
    info = to_error_info(FileNotFoundError("no such file"))
    assert info["code"] == "FILE_NOT_FOUND"
    assert info["exc_type"] == "FileNotFoundError"
    assert "not found" in info["message"]


def test_file_not_found_uses_filename_attr() -> None:
    exc = FileNotFoundError(2, "No such file or directory", "/data/foo.csv")
    info = to_error_info(exc)
    assert "/data/foo.csv" in info["message"]


def test_file_not_found_has_hint() -> None:
    info = to_error_info(FileNotFoundError("missing.csv"))
    assert info.get("hint") is not None
    assert "check the path" in (info.get("hint") or "")


# ── PermissionError ───────────────────────────────────────────────────────────


def test_permission_error_code() -> None:
    info = to_error_info(PermissionError("denied"))
    assert info["code"] == "PERMISSION_DENIED"
    assert info["exc_type"] == "PermissionError"
    assert "permission denied" in info["message"]


# ── UnicodeDecodeError ────────────────────────────────────────────────────────


def test_unicode_decode_error_code_and_message() -> None:
    exc = UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte")
    info = to_error_info(exc)
    assert info["code"] == "DECODE_ERROR"
    assert info["exc_type"] == "UnicodeDecodeError"
    assert "encoding" in info["message"]


def test_unicode_decode_error_detail_in_metadata() -> None:
    exc = UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "invalid start byte")
    info = to_error_info(exc)
    meta = info.get("metadata") or {}
    assert "detail" in meta
    assert "utf-8" in meta["detail"]


# ── ValueError ────────────────────────────────────────────────────────────────


def test_value_error_code_and_message() -> None:
    info = to_error_info(ValueError("bad value"))
    assert info["code"] == "VALUE_ERROR"
    assert info["message"] == "bad value"


def test_value_error_subclass_preserved() -> None:
    class MyValueError(ValueError):
        pass

    info = to_error_info(MyValueError("sub"))
    assert info["code"] == "VALUE_ERROR"
    assert info["exc_type"] == "MyValueError"


# ── Unknown / fallback ────────────────────────────────────────────────────────


def test_unknown_exception_fallback() -> None:
    info = to_error_info(RuntimeError("unexpected"))
    assert info["code"] == "INTERNAL_ERROR"
    assert info["exc_type"] == "RuntimeError"
    assert "unexpected" in info["message"]


def test_unknown_exception_empty_str_falls_back_to_repr() -> None:
    exc = RuntimeError()
    info = to_error_info(exc)
    assert info["code"] == "INTERNAL_ERROR"
    assert info["message"]  # non-empty — either str or repr


# ── ErrorInfo is dict-like ────────────────────────────────────────────────────


def test_error_info_is_subscriptable() -> None:
    info: ErrorInfo = to_error_info(DQTError("x"))
    assert info["code"] == "DQTERROR"
    assert isinstance(info, dict)
