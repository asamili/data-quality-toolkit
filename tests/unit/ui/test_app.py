"""Unit tests for data_quality_toolkit.ui.app — no live Streamlit required."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

from data_quality_toolkit.storage.connection import StorageError
from data_quality_toolkit.ui.app import _load_run_history


def test_module_imports_without_streamlit() -> None:
    """app module must be importable when Streamlit is absent (deferred import)."""
    import data_quality_toolkit.ui.app as _cached

    real_st = sys.modules.get("streamlit")
    sys.modules["streamlit"] = None  # type: ignore[assignment]
    try:
        del sys.modules["data_quality_toolkit.ui.app"]
        mod = importlib.import_module("data_quality_toolkit.ui.app")
        assert callable(mod.main)
    finally:
        if real_st is not None:
            sys.modules["streamlit"] = real_st
        else:
            sys.modules.pop("streamlit", None)
        sys.modules["data_quality_toolkit.ui.app"] = _cached


def test_main_is_callable() -> None:
    import data_quality_toolkit.ui.app as app

    assert callable(app.main)


def test_load_run_history_missing_db_returns_empty(tmp_path: Path) -> None:
    records, err = _load_run_history(str(tmp_path / "nonexistent.db"), "ds1")
    assert records == []
    assert err is None


def test_load_run_history_storage_error_returns_message(tmp_path: Path) -> None:
    with patch(
        "data_quality_toolkit.ui.app.read_run_history",
        side_effect=StorageError("db corrupt"),
    ):
        records, err = _load_run_history(str(tmp_path / "some.db"), "ds1")
    assert records is None
    assert err is not None
    assert "db corrupt" in err


def test_load_run_history_strips_input_whitespace(tmp_path: Path) -> None:
    path_with_spaces = "  " + str(tmp_path / "nonexistent.db") + "  "
    records, err = _load_run_history(path_with_spaces, " ds1 ")
    assert records == []
    assert err is None
