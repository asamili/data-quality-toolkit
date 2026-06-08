"""Unit tests for data_quality_toolkit.shared.path_guard."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit.shared.path_guard import (
    PathGuardError,
    ensure_safe_output_dir,
    validate_output_dir,
)


def test_validate_safe_absolute_accepted(tmp_path: Path) -> None:
    new_dir = tmp_path / "new_output"
    result = validate_output_dir(new_dir)
    assert result == new_dir.resolve()
    assert not new_dir.exists()


def test_validate_existing_dir_accepted(tmp_path: Path) -> None:
    result = validate_output_dir(tmp_path)
    assert result == tmp_path.resolve()


def test_validate_relative_path_rejected() -> None:
    with pytest.raises(PathGuardError, match="absolute"):
        validate_output_dir("relative/path")


def test_validate_relative_dot_slash_rejected() -> None:
    with pytest.raises(PathGuardError, match="absolute"):
        validate_output_dir("./relative")


def test_validate_traversal_rejected() -> None:
    with pytest.raises(PathGuardError, match="traversal"):
        validate_output_dir("/safe/output/../../../etc")


def test_validate_traversal_in_middle_rejected() -> None:
    with pytest.raises(PathGuardError, match="traversal"):
        validate_output_dir("/safe/../other")


def test_validate_file_path_rejected(tmp_path: Path) -> None:
    f = tmp_path / "existing_file.txt"
    f.write_text("content")
    with pytest.raises(PathGuardError, match="file"):
        validate_output_dir(f)


def test_validate_empty_string_rejected() -> None:
    with pytest.raises(PathGuardError, match="empty"):
        validate_output_dir("")


def test_validate_whitespace_only_rejected() -> None:
    with pytest.raises(PathGuardError, match="empty"):
        validate_output_dir("   ")


def test_validate_must_be_absolute_false_accepts_relative(tmp_path: Path) -> None:
    import os

    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = validate_output_dir("relative_dir", must_be_absolute=False)
        assert result == (tmp_path / "relative_dir").resolve()
    finally:
        os.chdir(old_cwd)


def test_validate_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    parent_dir = tmp_path / "safe" / "parent"
    parent_dir.mkdir(parents=True)
    link = parent_dir / "escape"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not supported on this platform/configuration")
    with pytest.raises(PathGuardError, match="[Ss]ymlink"):
        validate_output_dir(link)


def test_ensure_safe_no_create_nonexistent_ok(tmp_path: Path) -> None:
    new_dir = tmp_path / "nonexistent"
    result = ensure_safe_output_dir(new_dir, create=False)
    assert result == new_dir.resolve()
    assert not new_dir.exists()


def test_ensure_safe_creates_when_requested(tmp_path: Path) -> None:
    new_dir = tmp_path / "to_create" / "nested"
    result = ensure_safe_output_dir(new_dir, create=True)
    assert result == new_dir.resolve()
    assert new_dir.exists()
    assert new_dir.is_dir()


def test_ensure_safe_rejects_relative_path() -> None:
    with pytest.raises(PathGuardError, match="absolute"):
        ensure_safe_output_dir("relative/path")


def test_ensure_safe_rejects_traversal() -> None:
    with pytest.raises(PathGuardError, match="traversal"):
        ensure_safe_output_dir("/safe/../etc")


def test_ensure_safe_existing_dir_no_recreate(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    result = ensure_safe_output_dir(existing, create=True)
    assert result == existing.resolve()
    assert existing.is_dir()
