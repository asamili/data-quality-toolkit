from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Protocol


class StorageError(Exception):
    pass


class _HasExportBaseDir(Protocol):
    export_base_dir: Path


def _get_db_path(settings: _HasExportBaseDir) -> Path:
    override = os.environ.get("DQT_DB_PATH")
    if override:
        return Path(override)
    return Path(settings.export_base_dir) / "dqt.db"


def connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con
