from __future__ import annotations

import importlib

import pytest

from data_quality_toolkit.shared.exceptions import DQTError, ValidationError  # adjust names


def test_custom_exceptions_str_and_raise():
    e = DQTError("boom")
    assert "boom" in str(e)
    with pytest.raises(DQTError):
        raise DQTError("boom2")


def test_validation_error_subclassing():
    assert issubclass(ValidationError, DQTError)


def test_constants_values_and_exports():
    const = importlib.import_module("data_quality_toolkit.shared.constants")

    # Basic values — VERSION derives from installed package metadata (DQT-FIX-004)
    from importlib.metadata import version as _pkg_version

    assert const.VERSION == _pkg_version("data-quality-toolkit")
    assert const.DEFAULT_TS_FORMAT.endswith("Z")
    assert const.DEFAULT_MAX_ROWS_IN_MEMORY > 0
    assert const.DEFAULT_SAMPLE_SIZE > 0
    assert 0 < const.DEFAULT_NULL_THRESHOLD < 1
    assert 0 < const.DEFAULT_UNIQUENESS_THRESHOLD < 1
    assert {"low", "medium", "high", "critical"}.issubset(set(const.SEVERITY_LEVELS))

    # __all__ export surface sanity
    for name in const.__all__:
        assert hasattr(const, name), f"Exported {name} missing on module"


def test_exceptions_hierarchy_and_raise():
    exc = importlib.import_module("data_quality_toolkit.shared.exceptions")

    # Hierarchy
    assert issubclass(exc.DQTError, Exception)
    for sub in (
        exc.LoaderError,
        exc.ValidationError,
        exc.ConfigError,
        exc.ProfileError,
        exc.AssessmentError,
    ):
        assert issubclass(sub, exc.DQTError)

    # Raising & catching
    try:
        raise exc.ConfigError("bad config")
    except exc.DQTError as e:
        assert "bad config" in str(e)


def test_settings_defaults_from_constants(tmp_path, monkeypatch):
    # Unset env to ensure defaults are used; isolate from .env files and CWD writes
    monkeypatch.delenv("DQT_LOAD_ENV", raising=False)
    monkeypatch.delenv("MAX_ROWS_IN_MEMORY", raising=False)
    monkeypatch.delenv("SAMPLE_SIZE", raising=False)
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "dist"))

    from data_quality_toolkit.shared.constants import (
        DEFAULT_MAX_ROWS_IN_MEMORY,
        DEFAULT_SAMPLE_SIZE,
    )
    from data_quality_toolkit.shared.settings import load_settings

    s = load_settings()
    assert s.max_rows_in_memory == DEFAULT_MAX_ROWS_IN_MEMORY
    assert s.sample_size == DEFAULT_SAMPLE_SIZE
