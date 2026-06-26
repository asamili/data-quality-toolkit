# tests/unit/exporters/test_drift_xlsx_exporter.py
"""Unit tests for the drift-history .xlsx exporter.

The exporter splits a pure, openpyxl-free model builder from the thin openpyxl
writer, so most behavior (escaping, sheet selection, headers, row counts, path
safety, missing-dependency guard) is testable without the optional [powerbi]
extra installed. On-disk workbook tests are gated behind ``importorskip``.
"""

from __future__ import annotations

import sys

import pytest

from data_quality_toolkit.adapters.exporters.bi import xlsx_drift_exporter as xe
from data_quality_toolkit.adapters.exporters.bi.xlsx_drift_exporter import (
    XlsxExportError,
    build_workbook_model,
    escape_formula,
    export_drift_history_xlsx,
)
from data_quality_toolkit.shared.exceptions import DQTError

# --- escape_formula ---


@pytest.mark.parametrize(
    "value",
    ["=SUM(A1:A2)", "+1+1", "-1", "@cmd", "\t=1", "\r=1", "   =danger", "\t@evil"],
)
def test_escape_formula_neutralizes_dangerous(value: str) -> None:
    out = escape_formula(value)
    assert out == "'" + value


@pytest.mark.parametrize("value", ["run_id", "abc", "a=b", "1.5", "north-south is fine"])
def test_escape_formula_leaves_safe_unchanged(value: str) -> None:
    # "north-south" starts with 'n', not '-', so it is safe.
    assert escape_formula(value) == value


@pytest.mark.parametrize("value", [None, 0, 1, 2.5, True, "", -3])
def test_escape_formula_passes_non_strings_through(value: object) -> None:
    assert escape_formula(value) == value


# --- build_workbook_model ---

_RUNS = [{"run_id": "r1", "status": "ok", "drift_detected": 1, "current_dataset_id": "cd1"}]
_SUMMARY = {"total_runs": 1, "drift_rate": 0.0}
_COLUMNS = [{"run_id": "r1", "column_name": "age", "psi": 0.31}]
_DISTS = [{"run_id": "r1", "column_name": "age", "bin_index": 0, "bin_label": "[0, 1)"}]
_META = {"tool_version": "2.6.0", "db_path": "x.db"}


def test_model_default_includes_columns_not_distributions() -> None:
    model = build_workbook_model(
        runs=_RUNS, summary=_SUMMARY, columns=_COLUMNS, distributions=None, metadata=_META
    )
    assert list(model.keys()) == ["runs", "trend_summary", "columns", "metadata"]
    assert "distributions" not in model


def test_model_includes_distributions_when_provided() -> None:
    model = build_workbook_model(
        runs=_RUNS, summary=_SUMMARY, columns=_COLUMNS, distributions=_DISTS, metadata=_META
    )
    assert list(model.keys()) == [
        "runs",
        "trend_summary",
        "columns",
        "distributions",
        "metadata",
    ]


def test_model_excludes_columns_when_none() -> None:
    model = build_workbook_model(
        runs=_RUNS, summary=_SUMMARY, columns=None, distributions=None, metadata=_META
    )
    assert "columns" not in model


def test_model_headers_and_row_counts() -> None:
    model = build_workbook_model(
        runs=_RUNS, summary=_SUMMARY, columns=_COLUMNS, distributions=_DISTS, metadata=_META
    )
    assert model["runs"]["headers"][0] == "run_id"
    assert model["trend_summary"]["headers"] == ["key", "value"]
    assert model["runs"]["count"] == 1
    assert model["columns"]["count"] == 1
    assert model["distributions"]["count"] == 1
    assert model["trend_summary"]["count"] == len(_SUMMARY)
    # runs row follows header order
    run_row = model["runs"]["rows"][0]
    assert run_row[0] == "r1"  # run_id is first header


def test_model_escapes_dangerous_cell_values() -> None:
    runs = [{"run_id": "=DANGER()", "status": "ok"}]
    model = build_workbook_model(
        runs=runs, summary={}, columns=None, distributions=None, metadata={}
    )
    assert model["runs"]["rows"][0][0] == "'=DANGER()"


def test_model_empty_inputs_produce_zero_state_sheets() -> None:
    model = build_workbook_model(runs=[], summary={}, columns=[], distributions=None, metadata={})
    assert model["runs"]["count"] == 0
    assert model["columns"]["count"] == 0
    assert model["runs"]["rows"] == []


# --- path validation (no openpyxl needed) ---


def test_validate_output_path_rejects_empty() -> None:
    with pytest.raises(XlsxExportError, match="must not be empty"):
        xe._validate_output_path("   ", force=False)


def test_validate_output_path_requires_xlsx_extension(tmp_path) -> None:
    with pytest.raises(XlsxExportError, match=r"must end with .xlsx"):
        xe._validate_output_path(tmp_path / "out.csv", force=False)


def test_validate_output_path_rejects_traversal() -> None:
    with pytest.raises(XlsxExportError):
        xe._validate_output_path("../escape.xlsx", force=False)


def test_validate_output_path_refuses_overwrite_without_force(tmp_path) -> None:
    existing = tmp_path / "out.xlsx"
    existing.write_bytes(b"old")
    with pytest.raises(XlsxExportError, match="already exists"):
        xe._validate_output_path(existing, force=False)


def test_validate_output_path_allows_overwrite_with_force(tmp_path) -> None:
    existing = tmp_path / "out.xlsx"
    existing.write_bytes(b"old")
    resolved = xe._validate_output_path(existing, force=True)
    assert resolved.name == "out.xlsx"


def test_validate_output_path_rejects_directory_target(tmp_path) -> None:
    d = tmp_path / "adir.xlsx"
    d.mkdir()
    with pytest.raises(XlsxExportError, match="existing directory"):
        xe._validate_output_path(d, force=True)


# --- missing-dependency guard ---


def test_missing_openpyxl_raises_with_powerbi_hint(monkeypatch, tmp_path) -> None:
    # Force `import openpyxl` to fail regardless of install state.
    monkeypatch.setitem(sys.modules, "openpyxl", None)
    with pytest.raises(XlsxExportError) as ei:
        export_drift_history_xlsx(tmp_path / "m.db", tmp_path / "out.xlsx")
    msg = str(ei.value)
    assert "powerbi" in msg
    assert isinstance(ei.value, DQTError)


# --- on-disk workbook (requires the [powerbi] extra) ---


def test_export_writes_real_workbook_missing_db_zero_state(tmp_path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "drift.xlsx"
    missing_db = tmp_path / "nope.db"
    result = export_drift_history_xlsx(missing_db, out, include_distributions=True)

    assert result["output_path"] == str(out.resolve())
    assert out.exists()
    assert result["sheets"] == [
        "runs",
        "trend_summary",
        "columns",
        "distributions",
        "metadata",
    ]
    assert result["row_counts"]["runs"] == 0

    wb = openpyxl.load_workbook(out, read_only=True)
    assert set(wb.sheetnames) == {
        "runs",
        "trend_summary",
        "columns",
        "distributions",
        "metadata",
    }
    runs_ws = wb["runs"]
    header = [c.value for c in next(runs_ws.iter_rows(min_row=1, max_row=1))]
    assert header[0] == "run_id"
    wb.close()


def test_export_excludes_distributions_sheet_by_default(tmp_path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "drift.xlsx"
    result = export_drift_history_xlsx(tmp_path / "nope.db", out)
    assert "distributions" not in result["sheets"]
    wb = openpyxl.load_workbook(out, read_only=True)
    assert "distributions" not in wb.sheetnames
    wb.close()
