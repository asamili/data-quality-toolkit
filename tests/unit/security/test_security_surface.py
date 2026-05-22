"""Security-regression tests for DQT's documented local-tool boundaries.

These lock the security-relevant surface in place: path validation, loader
rejection of non-CSV inputs, and the safe-by-default settings posture
(network off, no credentials baked into defaults).
"""

from __future__ import annotations

import pytest

from data_quality_toolkit.loaders.file.csv_loader import load_csv
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.utils.validators import validate_csv_path


def test_validate_csv_path_accepts_real_csv(tmp_path):
    csv = tmp_path / "data.csv"
    csv.write_text("a,b\n1,2\n", encoding="utf-8")
    assert validate_csv_path(str(csv)) is True


def test_validate_csv_path_rejects_missing_file(tmp_path):
    assert validate_csv_path(str(tmp_path / "nope.csv")) is False


def test_validate_csv_path_rejects_non_csv_suffix(tmp_path):
    other = tmp_path / "data.txt"
    other.write_text("a,b\n1,2\n", encoding="utf-8")
    assert validate_csv_path(str(other)) is False


def test_validate_csv_path_rejects_directory(tmp_path):
    assert validate_csv_path(str(tmp_path)) is False


def test_loader_rejects_non_csv_suffix(tmp_path):
    other = tmp_path / "payload.txt"
    other.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_csv(str(other))


def test_loader_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_csv(str(tmp_path / "missing.csv"))


def test_settings_network_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DQT_ALLOW_NETWORK", raising=False)
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "dist"))
    settings = load_settings()
    assert settings.dqt_allow_network is False


def test_settings_api_key_not_baked_into_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "dist"))
    settings = load_settings()
    assert settings.api_key is None
