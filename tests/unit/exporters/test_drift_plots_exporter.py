# tests/unit/exporters/test_drift_plots_exporter.py
"""Unit tests for the drift-history PNG plot exporter.

The exporter splits a pure, matplotlib-free model builder from a lazy matplotlib
render layer, so most behavior (model math, chart selection, path safety,
missing-dependency guard) is testable without the optional [viz] extra installed.
On-disk PNG tests are gated behind ``importorskip("matplotlib")``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from data_quality_toolkit.adapters.exporters.viz import drift_plots as dp
from data_quality_toolkit.adapters.exporters.viz.drift_plots import (
    SUPPORTED_CHARTS,
    PlotExportError,
    build_plot_model,
    export_drift_plots,
)
from data_quality_toolkit.shared.exceptions import DQTError

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

# read_drift_runs returns newest-first; the model reverses to oldest-first.
_RUNS = [
    {"created_at": "2026-06-13T00:00:02+00:00", "columns_tested": 4, "columns_drifted": 2},
    {"created_at": "2026-06-13T00:00:01+00:00", "columns_tested": 4, "columns_drifted": 0},
]
_SUMMARY = {"drift_rate": 0.5}
_COLUMNS = [
    {"column_name": "a", "psi": 0.3, "drift_detected": 1},
    {"column_name": "b", "psi": 0.1, "drift_detected": 0},
    {"column_name": "a", "psi": 0.5, "drift_detected": 1},
]


# --- pure model builder ---


def test_build_plot_model_drift_rate_oldest_first() -> None:
    model = build_plot_model(runs=_RUNS, summary=_SUMMARY, columns=_COLUMNS)
    dr = model["drift-rate"]
    assert dr["values"] == [0.0, 0.5]  # reversed → oldest first
    assert dr["drift_rate"] == 0.5
    assert dr["count"] == 2


def test_build_plot_model_psi_mean_descending() -> None:
    model = build_plot_model(runs=_RUNS, summary=_SUMMARY, columns=_COLUMNS)
    psi = model["psi-by-column"]
    assert psi["labels"] == ["a", "b"]  # mean a=0.4 > b=0.1
    assert psi["values"] == [0.4, 0.1]
    assert psi["count"] == 2


def test_build_plot_model_top_drifted_counts() -> None:
    model = build_plot_model(runs=_RUNS, summary=_SUMMARY, columns=_COLUMNS)
    top = model["top-drifted"]
    assert top["labels"] == ["a"]  # only "a" drifted (twice)
    assert top["values"] == [2]
    assert top["count"] == 1


def test_build_plot_model_zero_state() -> None:
    model = build_plot_model(runs=[], summary={}, columns=[])
    assert model["drift-rate"]["count"] == 0
    assert model["drift-rate"]["drift_rate"] == 0.0
    assert model["psi-by-column"]["count"] == 0
    assert model["top-drifted"]["count"] == 0


def test_build_plot_model_skips_none_psi() -> None:
    cols = [{"column_name": "x", "psi": None, "drift_detected": 0}]
    model = build_plot_model(runs=[], summary={}, columns=cols)
    assert model["psi-by-column"]["count"] == 0


# --- chart selector ---


def test_resolve_charts_all() -> None:
    assert dp._resolve_charts("all") == SUPPORTED_CHARTS


def test_resolve_charts_single() -> None:
    assert dp._resolve_charts("drift-rate") == ("drift-rate",)


def test_resolve_charts_unknown_raises() -> None:
    with pytest.raises(PlotExportError):
        dp._resolve_charts("bogus")


# --- path safety ---


def test_unsafe_output_dir_traversal_rejected(tmp_path: Path) -> None:
    with pytest.raises(PlotExportError):
        export_drift_plots(tmp_path / "missing.db", str(tmp_path / ".." / "evil"))


def test_empty_output_dir_rejected() -> None:
    with pytest.raises(PlotExportError):
        export_drift_plots("m.db", "   ")


# --- missing-dependency guard (works whether or not matplotlib is installed) ---


def test_missing_matplotlib_raises_with_viz_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "matplotlib", None)  # force ImportError on import
    with pytest.raises(PlotExportError) as ei:
        dp._import_matplotlib()
    assert "viz" in str(ei.value)
    assert isinstance(ei.value, DQTError)


# --- matplotlib-gated render tests ---


def test_agg_backend_enforced() -> None:
    pytest.importorskip("matplotlib")
    dp._import_matplotlib()
    import matplotlib

    assert matplotlib.get_backend().lower() == "agg"


def test_export_all_writes_three_valid_pngs(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    db = tmp_path / "missing.db"  # nonexistent → zero-state, still valid PNGs
    out = tmp_path / "plots"
    result = export_drift_plots(db, out, chart="all")
    assert set(result["charts"]) == set(SUPPORTED_CHARTS)
    for path in result["charts"].values():
        p = Path(path)
        assert p.exists()
        assert p.read_bytes()[:8] == _PNG_MAGIC


def test_export_single_chart_writes_only_selected(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    db = tmp_path / "missing.db"
    out = tmp_path / "plots"
    result = export_drift_plots(db, out, chart="psi-by-column")
    assert set(result["charts"]) == {"psi-by-column"}
    assert (out / "psi_by_column.png").exists()
    assert not (out / "drift_rate.png").exists()


def test_no_overwrite_without_force_then_force(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    db = tmp_path / "missing.db"
    out = tmp_path / "plots"
    export_drift_plots(db, out, chart="drift-rate")
    with pytest.raises(PlotExportError) as ei:
        export_drift_plots(db, out, chart="drift-rate")
    assert "already exists" in str(ei.value)
    # force succeeds
    result = export_drift_plots(db, out, chart="drift-rate", force=True)
    assert Path(result["charts"]["drift-rate"]).exists()
