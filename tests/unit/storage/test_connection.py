from __future__ import annotations

from pathlib import Path

import pytest

from data_quality_toolkit.adapters.storage.connection import StorageError, _get_db_path, connect


class _FakeSettings:
    def __init__(self, base: Path) -> None:
        self.export_base_dir: Path = base


def test_default_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DQT_DB_PATH", raising=False)
    assert _get_db_path(_FakeSettings(tmp_path)) == tmp_path / "dqt.db"


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = tmp_path / "custom.db"
    monkeypatch.setenv("DQT_DB_PATH", str(override))
    assert _get_db_path(_FakeSettings(tmp_path)) == override


def test_foreign_keys_on(tmp_path: Path) -> None:
    con = connect(tmp_path / "test.db")
    try:
        row = con.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1
    finally:
        con.close()


def test_row_factory(tmp_path: Path) -> None:
    con = connect(tmp_path / "test.db")
    try:
        con.execute("CREATE TABLE t (x INTEGER)")
        con.execute("INSERT INTO t VALUES (42)")
        con.commit()
        row = con.execute("SELECT x FROM t").fetchone()
        assert row["x"] == 42
    finally:
        con.close()


def test_storage_error_is_exception() -> None:
    with pytest.raises(StorageError):
        raise StorageError("test")
