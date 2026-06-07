"""Tests for unsupported file extension validation in the CLI."""

from types import SimpleNamespace

import pytest

import data_quality_toolkit.adapters.cli.main as cli

# --- Unit tests for the helper directly ---


@pytest.mark.parametrize(
    "path",
    [
        "data.txt",
        "data.xlsx",
        "data.parquet",
        "data.json",
        "data.tsv",
        "data",  # no extension
        "/data/file.xls",
        "C:\\data\\file.tsv",
    ],
)
def test_unsupported_extension_returns_message(path):
    args = SimpleNamespace(csv=path)
    result = cli._validate_csv_extension(args)
    assert result is not None
    assert "Unsupported" in result or "unsupported" in result.lower()


@pytest.mark.parametrize(
    "path",
    [
        "data.csv",
        "my_file.CSV",  # case-insensitive
        "/data/my_file.csv",
        "C:\\Users\\data.CSV",
    ],
)
def test_supported_extension_returns_none(path):
    args = SimpleNamespace(csv=path)
    assert cli._validate_csv_extension(args) is None


def test_no_csv_attr_is_safe():
    args = SimpleNamespace()
    assert cli._validate_csv_extension(args) is None


def test_blank_path_deferred_to_other_validator():
    # Blank paths are handled by _validate_csv_path; extension validator skips them
    args = SimpleNamespace(csv="   ")
    assert cli._validate_csv_extension(args) is None


def test_no_extension_message_shows_none_label():
    args = SimpleNamespace(csv="datafile")
    result = cli._validate_csv_extension(args)
    assert result is not None
    assert "(none)" in result


# --- Integration tests through main() ---


@pytest.mark.parametrize("bad_path", ["data.txt", "file.xlsx", "archive.zip"])
def test_main_rejects_unsupported_extension(monkeypatch, bad_path, capsys):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    rc = cli.main(["profile", bad_path])
    assert rc == 2
    assert "Error:" in capsys.readouterr().err


def test_main_accepts_csv_extension(monkeypatch):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    monkeypatch.setattr(cli, "run_profile", lambda *a, **kw: {"columns": []})
    rc = cli.main(["profile", "data.csv"])
    assert rc != 2  # extension guard did not fire
