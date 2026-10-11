r"""Focused tests for bounded, safe artifact previews.

The path-redaction tests below use example absolute paths (Windows
``C:\example_owner\...`` and POSIX ``/home/example_owner/...``) purely as
*fixtures*: each asserts the owner and repository-root segments are stripped
from the text the dashboard renders, proving the redaction. No real private path
is emitted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit.adapters.ui.services import artifact_previews
from data_quality_toolkit.adapters.ui.services.artifact_previews import (
    file_size,
    human_size,
    preview_file,
    read_bounded_bytes,
)

# Synthetic stand-ins for a private checkout: an owner-named directory under a
# drive letter, and its POSIX-shaped equivalent.
_WINDOWS_PRIVATE_PATH = r"C:\example_owner\private_repo_root\secret.csv"
_POSIX_PRIVATE_PATH = "/home/example_owner/private_repo_root/secret.csv"


def _assert_private_path_not_disclosed(text: str, *, posix: bool = False) -> None:
    """The leaf may show; the owner and repository-root segments may not."""
    assert "secret.csv" in text
    assert "example_owner" not in text
    assert "private_repo_root" not in text
    if posix:
        assert "/home" not in text
    else:
        assert "C:\\" not in text


# ── human_size / file_size ───────────────────────────────────────────────────


def test_human_size_units() -> None:
    assert human_size(None) == "unknown"
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024**2) == "5.0 MB"


def test_file_size_present_and_missing(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello", encoding="utf-8")
    assert file_size(str(p)) == 5
    assert file_size(str(tmp_path / "missing.txt")) is None


# ── read_bounded_bytes ───────────────────────────────────────────────────────


def test_read_bounded_bytes_ok(tmp_path: Path) -> None:
    p = tmp_path / "a.bin"
    p.write_bytes(b"abc")
    data, err = read_bounded_bytes(str(p))
    assert err is None
    assert data == b"abc"


def test_read_bounded_bytes_missing(tmp_path: Path) -> None:
    data, err = read_bounded_bytes(str(tmp_path / "missing.bin"))
    assert data is None
    assert err == "file not available"


def test_read_bounded_bytes_too_large(tmp_path: Path) -> None:
    p = tmp_path / "big.bin"
    p.write_bytes(b"0123456789")
    data, err = read_bounded_bytes(str(p), max_bytes=1)
    assert data is None
    assert err is not None
    assert "too large" in err


# ── preview_file ─────────────────────────────────────────────────────────────


def test_preview_csv(tmp_path: Path) -> None:
    p = tmp_path / "t.csv"
    p.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    result = preview_file(str(p))
    assert result["kind"] == "csv"
    assert result["error"] is None
    assert list(result["data"].columns) == ["a", "b"]
    assert result["rows"] == 2


def test_preview_json(tmp_path: Path) -> None:
    p = tmp_path / "t.json"
    p.write_text('{"k": [1, 2, 3]}', encoding="utf-8")
    result = preview_file(str(p))
    assert result["kind"] == "json"
    assert result["data"] == {"k": [1, 2, 3]}


def test_preview_invalid_json_degrades_to_text(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    result = preview_file(str(p))
    assert result["kind"] == "text"
    assert "not valid json" in result["text"]


def test_preview_text(tmp_path: Path) -> None:
    p = tmp_path / "t.md"
    p.write_text("# heading\nbody", encoding="utf-8")
    result = preview_file(str(p))
    assert result["kind"] == "text"
    assert "heading" in result["text"]


def test_preview_text_truncates(tmp_path: Path) -> None:
    p = tmp_path / "t.txt"
    p.write_text("x" * 100, encoding="utf-8")
    result = preview_file(str(p), max_bytes=10)
    assert result["kind"] == "text"
    assert "truncated" in result["text"]


def test_preview_binary(tmp_path: Path) -> None:
    p = tmp_path / "t.pbit"
    p.write_bytes(b"\x00\x01\x02\x03")
    result = preview_file(str(p))
    assert result["kind"] == "binary"
    assert result["size"] == 4


def test_preview_missing(tmp_path: Path) -> None:
    result = preview_file(str(tmp_path / "nope.csv"))
    assert result["kind"] == "missing"
    assert result["error"] == "file not available"


# ── human-facing error redaction (shared redaction contract) ─────────────────
#
# Every string these functions return is rendered by the dashboard as a caption
# or a code block, so an exception naming the file it failed on must not carry
# the surrounding directories to the screen.


@pytest.mark.parametrize(
    ("private_path", "posix"),
    [(_WINDOWS_PRIVATE_PATH, False), (_POSIX_PRIVATE_PATH, True)],
)
def test_read_bounded_bytes_error_redacts_private_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private_path: str, posix: bool
) -> None:
    """``read_bounded_bytes`` reports an OSError without the private directories."""
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"abc")

    def _boom(self: Path) -> bytes:
        raise PermissionError(13, "Permission denied", private_path)

    monkeypatch.setattr(Path, "read_bytes", _boom)
    data, err = read_bounded_bytes(str(target))
    assert data is None
    assert err is not None
    _assert_private_path_not_disclosed(err, posix=posix)
    # Useful, non-sensitive context survives.
    assert "Permission denied" in err


@pytest.mark.parametrize(
    ("private_path", "posix"),
    [(_WINDOWS_PRIVATE_PATH, False), (_POSIX_PRIVATE_PATH, True)],
)
def test_text_preview_read_failure_redacts_private_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private_path: str, posix: bool
) -> None:
    """The failure notice shown *as* the text preview body is redacted."""
    target = tmp_path / "notes.md"
    target.write_text("body", encoding="utf-8")

    def _boom(self: Path, **kwargs: object) -> str:
        raise OSError(5, "Input/output error", private_path)

    monkeypatch.setattr(Path, "read_text", _boom)
    result = preview_file(str(target))
    assert result["kind"] == "text"
    assert result["error"] is None
    _assert_private_path_not_disclosed(result["text"], posix=posix)
    assert "could not read file" in result["text"]


@pytest.mark.parametrize(
    ("private_path", "posix"),
    [(_WINDOWS_PRIVATE_PATH, False), (_POSIX_PRIVATE_PATH, True)],
)
def test_csv_preview_error_redacts_private_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, private_path: str, posix: bool
) -> None:
    """A parser failure naming the file it read is captioned without the path."""
    target = tmp_path / "rows.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")

    def _boom(*args: object, **kwargs: object) -> object:
        raise ValueError(f"could not parse {private_path}")

    monkeypatch.setattr(artifact_previews.pd, "read_csv", _boom)
    result = preview_file(str(target))
    assert result["kind"] == "csv"
    assert result["error"] is not None
    _assert_private_path_not_disclosed(result["error"], posix=posix)


def test_csv_preview_error_without_a_path_is_preserved_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redaction scrubs paths only -- it must not blunt an ordinary parser message."""
    target = tmp_path / "rows.csv"
    target.write_text("a,b\n1,2\n", encoding="utf-8")
    message = "No columns to parse from file"

    def _boom(*args: object, **kwargs: object) -> object:
        raise ValueError(message)

    monkeypatch.setattr(artifact_previews.pd, "read_csv", _boom)
    assert preview_file(str(target))["error"] == message


def test_bounded_status_strings_are_not_exception_derived(tmp_path: Path) -> None:
    """The module's own literals stay exact; only exception text is scrubbed."""
    assert preview_file(str(tmp_path / "gone.csv"))["error"] == "file not available"
    big = tmp_path / "big.bin"
    big.write_bytes(b"0123456789")
    _, err = read_bounded_bytes(str(big), max_bytes=1)
    assert err == "file too large to download here (10 B)"
