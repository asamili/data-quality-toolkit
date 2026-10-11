"""Tests for UI error-message path redaction parity.

Covers ``redact_message_paths`` (the shared scrubber) and ``show_error`` (the
central banner that routes through it). The redaction inputs below intentionally
use example absolute paths (Windows ``C:\\Users\\...`` and POSIX ``/home/...``)
purely as *fixtures*: each test asserts the raw directory/username is stripped
from the output, proving the redaction — no real private path is emitted.
"""

from __future__ import annotations

from typing import Any

from data_quality_toolkit.adapters.ui.components.errors import (
    redact_message_paths,
    show_error,
)


class _RecordingSt:
    """Minimal Streamlit double that records error-banner calls."""

    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)


# --- redact_message_paths -------------------------------------------------


def test_windows_absolute_path_reduced_to_basename() -> None:
    out = redact_message_paths(r"could not load C:\Users\example_user\private\customers.csv now")
    assert "customers.csv" in out
    assert "C:\\" not in out
    assert "example_user" not in out
    assert "private" not in out
    assert "Users" not in out


def test_quoted_windows_path_keeps_quotes_and_wording() -> None:
    out = redact_message_paths(r"file not found: 'C:\Users\example_user\private\customers.csv'")
    assert out == "file not found: 'customers.csv'"


def test_posix_absolute_path_reduced_to_basename() -> None:
    out = redact_message_paths("file not found: '/home/user/data/customers.csv'")
    assert out == "file not found: 'customers.csv'"
    assert "/home" not in out
    assert "user" not in out


def test_unc_path_reduced_to_basename() -> None:
    out = redact_message_paths(r"denied \\fileserver\share\reports\model.tmsl.json")
    assert "model.tmsl.json" in out
    assert "fileserver" not in out
    assert "share" not in out


def test_bare_windows_root_is_fully_redacted() -> None:
    assert (
        redact_message_paths(r"root C:\ is not writable") == "root [path redacted] is not writable"
    )


def test_private_repo_root_is_redacted() -> None:
    # Synthetic stand-in for a developer's checkout root: an owner-named
    # directory under a drive letter. Both segments must disappear.
    out = redact_message_paths(
        r"permission denied: C:\example_owner\private_repo_root\dqt_metadata.db"
    )
    assert "dqt_metadata.db" in out
    assert "example_owner" not in out
    assert "private_repo_root" not in out


def test_plain_message_without_path_is_unchanged() -> None:
    msg = "time data '2020-13-01' does not match format '%Y-%m-%d'"
    assert redact_message_paths(msg) == msg


def test_fraction_and_slash_words_are_not_mangled() -> None:
    assert redact_message_paths("ratio 0/1 exceeded") == "ratio 0/1 exceeded"
    assert redact_message_paths("read/write conflict and/or retry") == (
        "read/write conflict and/or retry"
    )


def test_url_is_not_corrupted() -> None:
    msg = "webhook failed for https://host.example/api/v1/notify (timeout)"
    assert redact_message_paths(msg) == msg


def test_falsy_input_returns_empty_string() -> None:
    assert redact_message_paths(None) == ""
    assert redact_message_paths("") == ""


def test_basename_preserved_for_relative_reference() -> None:
    # A bare filename (no directory) is already safe and must survive intact.
    assert redact_message_paths("could not open report.csv") == "could not open report.csv"


# --- show_error -----------------------------------------------------------


def test_show_error_uses_banner_format_and_redacts_path() -> None:
    st: Any = _RecordingSt()
    show_error(st, "Load Error", r"file not found: 'C:\Users\example_user\private\customers.csv'")
    assert len(st.errors) == 1
    rendered = st.errors[0]
    assert rendered.startswith("⚠️ Load Error:")
    assert "customers.csv" in rendered
    assert "example_user" not in rendered
    assert "C:\\" not in rendered


def test_show_error_preserves_non_path_detail() -> None:
    st: Any = _RecordingSt()
    show_error(st, "Assessment Error", "column 'age' is not numeric")
    assert st.errors == ["⚠️ Assessment Error: column 'age' is not numeric"]
