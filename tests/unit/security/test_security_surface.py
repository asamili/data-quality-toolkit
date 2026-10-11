"""Security-regression tests for DQT's documented local-tool boundaries.

These lock the security-relevant surface in place: path validation, loader
rejection of non-CSV inputs, and the safe-by-default settings posture
(network off, no credentials baked into defaults).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from data_quality_toolkit.adapters.cli.main import cmd_settings_show
from data_quality_toolkit.adapters.loaders.file.csv_loader import load_csv
from data_quality_toolkit.shared.settings import load_settings
from data_quality_toolkit.utils.validators import validate_csv_path

_ENV_EXAMPLE = Path(__file__).resolve().parents[3] / ".env.example"
_CREDENTIAL_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSW|CREDENTIAL|AUTH", re.IGNORECASE)
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


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


def test_settings_expose_no_credential_fields(tmp_path, monkeypatch, capsys):
    """No setting holds a credential, so `dqt settings show` cannot echo one."""
    sentinel = "DQT_TEST_SENTINEL_VALUE"
    monkeypatch.delenv("DQT_LOAD_ENV", raising=False)
    monkeypatch.setenv("API_KEY", sentinel)
    monkeypatch.setenv("EXPORT_BASE_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv("PBI_BASE_FOLDER_PARAMETER", str(tmp_path / "dist"))

    settings = load_settings()
    assert [name for name in dict(settings) if _CREDENTIAL_NAME.search(name)] == []

    assert cmd_settings_show(argparse.Namespace()) == 0
    shown = capsys.readouterr().out
    assert sentinel not in shown
    assert "api_key" not in shown


def test_env_example_template_carries_no_credentials():
    if not _ENV_EXAMPLE.is_file():
        pytest.skip("the private .env.example template is not present in this tree")
    checked = 0
    for line in _ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        # Commented examples count too: uncommenting one must not add a secret.
        name, sep, value = line.lstrip("#").strip().partition("=")
        if not sep or not _ENV_NAME.fullmatch(name):
            continue
        checked += 1
        assert not _CREDENTIAL_NAME.search(name), line
        assert "://" not in value, line
    assert checked > 0
