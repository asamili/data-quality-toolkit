"""Optional dependency boundary contracts.

Documents the absence-behavior for each optional dep:
- scipy [stats]: detect_drift_frames returns status="unavailable" (no ImportError)
- duckdb [duckdb]: export_monitoring_duckdb raises DuckdbExportError with install hint
- orjson: PydanticSerializer falls back to stdlib json (use_orjson stays False)

Streamlit [ui] boundary is covered by tests/unit/cli/test_cli_ui.py.
"""

from __future__ import annotations

import pytest


class TestScipy:
    def test_scipy_absent_import_helper_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from data_quality_toolkit.domain.statistics import drift as drift_mod

        monkeypatch.setattr(drift_mod, "_import_scipy_stats", lambda: None)
        assert drift_mod._import_scipy_stats() is None

    def test_detect_drift_frames_scipy_absent_returns_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pandas as pd

        from data_quality_toolkit.domain.statistics import drift as drift_mod

        monkeypatch.setattr(drift_mod, "_import_scipy_stats", lambda: None)
        ref = pd.DataFrame({"age": [1, 2, 3, 4, 5]})
        cur = pd.DataFrame({"age": [10, 20, 30, 40, 50]})
        result = drift_mod.detect_drift_frames(ref, cur)
        assert result["status"] == "unavailable"
        assert result["scipy_available"] is False
        assert result["columns"] == []


class TestDuckdb:
    def test_duckdb_absent_raises_duckdb_export_error_with_hint(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from data_quality_toolkit.adapters.exporters.bi.duckdb_exporter import (
            DuckdbExportError,
            _import_duckdb,
        )

        monkeypatch.setitem(__import__("sys").modules, "duckdb", None)
        with pytest.raises(DuckdbExportError) as exc_info:
            _import_duckdb()
        msg = str(exc_info.value)
        assert "duckdb" in msg
        assert "pip install" in msg


class TestOrjson:
    def test_orjson_absent_pydantic_serializer_falls_back_to_stdlib(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import data_quality_toolkit.lineage.manifest.pydantic_impl as mod
        from data_quality_toolkit.lineage.manifest.pydantic_impl import PydanticSerializer

        monkeypatch.setattr(mod, "orjson", None)
        ser = PydanticSerializer(use_orjson=True)
        assert ser._use_orjson is False
