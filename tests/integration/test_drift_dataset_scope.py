"""Cross-dataset scope regression tests for drift column/distribution detail.

A monitoring DB holds independent drift history for two datasets that share a
column name. Whenever the drift runs are filtered (``current_dataset_id`` and/or
``limit``), every surface that renders column-level or distribution detail next
to those runs must source that detail from exactly the same runs: the CLI
report/dashboard/export-xlsx/plot commands, the report/dashboard builders, the
XLSX exporter, and the PNG plot exporter. Unfiltered output stays database-wide,
and a filter matching no runs never falls back to global detail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import data_quality_toolkit.adapters.cli.main as cli
import data_quality_toolkit.api as api
from data_quality_toolkit.adapters.reports.drift_history import build_drift_history_report
from data_quality_toolkit.adapters.storage import queries
from data_quality_toolkit.adapters.storage.connection import connect
from data_quality_toolkit.adapters.storage.schema import ensure_db

# --- Fixture data -------------------------------------------------------------

_RUNS = [
    # (run_id, created_at, current_dataset_id, columns_tested, columns_drifted)
    ("run-a1", "2026-06-13T00:00:01+00:00", "ds_alpha", 3, 1),
    ("run-b1", "2026-06-13T00:00:02+00:00", "ds_beta", 2, 2),
    ("run-a2", "2026-06-13T00:00:03+00:00", "ds_alpha", 1, 1),
]

_COLUMNS = [
    # (run_id, column_name, drift_detected, psi) -- every psi value is unique.
    ("run-a1", "colA_only", 1, 0.1111),
    ("run-a1", "colA_extra", 0, 0.1212),
    ("run-a1", "shared_col", 0, 0.4242),
    ("run-b1", "colB_only", 1, 0.8686),
    ("run-b1", "shared_col", 1, 0.9797),
    ("run-a2", "shared_col", 1, 0.5353),
]

_DISTRIBUTIONS = [
    # (run_id, column_name, bin_index, bin_label, reference_prob, current_prob)
    ("run-a1", "shared_col", 0, "binA-shared", 0.25, 0.35),
    ("run-a1", "colA_only", 0, "binA-only", 0.5, 0.5),
    ("run-b1", "shared_col", 0, "binB-shared", 0.75, 0.85),
    ("run-b1", "colB_only", 0, "binB-only", 0.6, 0.4),
    ("run-a2", "shared_col", 0, "binA2-shared", 0.3, 0.3),
]

_ALPHA = {"run-a1", "run-a2"}
_BETA = {"run-b1"}
_ALL = {r[0] for r in _RUNS}

# (run filter kwargs, run IDs the filter selects)
_CASES = [
    pytest.param({"current_dataset_id": "ds_alpha"}, _ALPHA, id="dataset-alpha"),
    pytest.param({"current_dataset_id": "ds_beta"}, _BETA, id="dataset-beta"),
    pytest.param({"limit": 1}, {"run-a2"}, id="limit-newest"),
    pytest.param({"current_dataset_id": "ds_beta", "limit": 1}, _BETA, id="dataset-and-limit"),
    pytest.param({}, _ALL, id="unfiltered"),
    pytest.param({"current_dataset_id": "ds_missing"}, set(), id="empty-filter"),
]


def _build_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "monitoring.db"
    ensure_db(db_path)
    with connect(db_path) as con:
        for run_id, created_at, dataset, tested, drifted in _RUNS:
            con.execute(
                """
                INSERT INTO drift_runs(
                    run_id, created_at, baseline_path, current_path,
                    baseline_dataset_id, current_dataset_id, status, alpha,
                    columns_tested, columns_skipped, columns_drifted,
                    drift_detected, report_path, schema_version
                ) VALUES (?, ?, 'b.csv', 'c.csv', 'base', ?, 'ok', 0.05, ?, 0, ?, 1, NULL, '1')
                """,
                (run_id, created_at, dataset, tested, drifted),
            )
        for run_id, column_name, drift_detected, psi in _COLUMNS:
            con.execute(
                """
                INSERT INTO drift_columns(
                    run_id, column_name, kind, test, statistic, p_value,
                    drift_detected, reference_n, current_n, status, skip_reason,
                    psi, js_distance, wasserstein
                ) VALUES (?, ?, 'numeric', 'ks', 0.5, 0.01, ?, 100, 100, 'tested', NULL,
                          ?, NULL, NULL)
                """,
                (run_id, column_name, drift_detected, psi),
            )
        for row in _DISTRIBUTIONS:
            con.execute(
                """
                INSERT INTO drift_column_distributions(
                    run_id, column_name, kind, bin_index, bin_label,
                    reference_prob, current_prob
                ) VALUES (?, ?, 'numeric', ?, ?, ?, ?)
                """,
                row,
            )
        con.commit()
    return db_path


# --- Expectations derived from the fixture ------------------------------------


def _column_names(eligible: set[str], *, drifted_only: bool = False) -> set[str]:
    return {c[1] for c in _COLUMNS if c[0] in eligible and (c[2] or not drifted_only)}


def _shared_psi(eligible: set[str]) -> set[float]:
    return {c[3] for c in _COLUMNS if c[0] in eligible and c[1] == "shared_col"}


def _markers(eligible: set[str]) -> tuple[set[str], set[str]]:
    """Text that must appear / must not appear for a surface scoped to ``eligible``."""
    names_in = _column_names(eligible)
    present = names_in | {d[3] for d in _DISTRIBUTIONS if d[0] in eligible}
    absent = (
        ({c[1] for c in _COLUMNS if c[0] not in eligible} - names_in)
        | {d[3] for d in _DISTRIBUTIONS if d[0] not in eligible}
        | {repr(c[3]) for c in _COLUMNS if c[0] not in eligible}
        | {r[0] for r in _RUNS if r[0] not in eligible}
    )
    return present, absent


def _assert_scoped_text(text: str, eligible: set[str]) -> None:
    present, absent = _markers(eligible)
    for marker in sorted(present):
        assert marker in text, f"expected {marker!r} in scoped output"
    for marker in sorted(absent):
        assert marker not in text, f"{marker!r} leaked from a non-eligible run"


def _cli_filter_args(kwargs: dict[str, Any]) -> list[str]:
    args: list[str] = []
    if "current_dataset_id" in kwargs:
        args += ["--current-dataset-id", kwargs["current_dataset_id"]]
    if "limit" in kwargs:
        args += ["--limit", str(kwargs["limit"])]
    return args


# --- Storage/API seam: run_ids scoping ----------------------------------------


@pytest.mark.parametrize(
    ("dataset", "eligible"), [("ds_alpha", _ALPHA), ("ds_beta", _BETA)], ids=["alpha", "beta"]
)
def test_readers_scope_detail_to_filtered_runs(tmp_path, dataset, eligible):
    db = _build_db(tmp_path)
    run_ids = [r["run_id"] for r in api.read_drift_runs_sqlite(db, current_dataset_id=dataset)]
    assert set(run_ids) == eligible

    columns = api.read_drift_columns_sqlite(db, run_ids=run_ids)
    assert {c["run_id"] for c in columns} == eligible
    assert {c["column_name"] for c in columns} == _column_names(eligible)
    shared = {c["psi"] for c in columns if c["column_name"] == "shared_col"}
    assert shared == _shared_psi(eligible)

    distributions = api.read_drift_distributions_sqlite(db, run_ids=run_ids)
    assert {d["run_id"] for d in distributions} == eligible
    assert {d["bin_label"] for d in distributions} == {
        d[3] for d in _DISTRIBUTIONS if d[0] in eligible
    }


def test_empty_run_ids_match_nothing(tmp_path):
    db = _build_db(tmp_path)
    assert api.read_drift_columns_sqlite(db, run_ids=[]) == []
    assert api.read_drift_distributions_sqlite(db, run_ids=[]) == []


def test_run_ids_none_keeps_database_wide_read(tmp_path):
    db = _build_db(tmp_path)
    assert api.read_drift_columns_sqlite(db, run_ids=None) == api.read_drift_columns_sqlite(db)
    assert len(api.read_drift_columns_sqlite(db)) == len(_COLUMNS)
    assert api.read_drift_distributions_sqlite(
        db, run_ids=None
    ) == api.read_drift_distributions_sqlite(db)
    assert len(api.read_drift_distributions_sqlite(db)) == len(_DISTRIBUTIONS)


def test_run_ids_combine_with_column_filter(tmp_path):
    db = _build_db(tmp_path)
    rows = api.read_drift_columns_sqlite(db, column_name="shared_col", run_ids=sorted(_ALPHA))
    assert {r["psi"] for r in rows} == _shared_psi(_ALPHA)
    bins = api.read_drift_distributions_sqlite(db, column_name="shared_col", run_ids=sorted(_BETA))
    assert [b["bin_label"] for b in bins] == ["binB-shared"]


def test_chunked_run_scope_matches_single_query_order(tmp_path, monkeypatch):
    db = _build_db(tmp_path)
    # Unordered, duplicated, and unknown IDs; chunk size 1 forces one query per run.
    requested = ["run-a2", "run-a1", "run-a1", "run-missing"]
    expected_cols = [r for r in api.read_drift_columns_sqlite(db) if r["run_id"] in _ALPHA]
    expected_dist = [r for r in api.read_drift_distributions_sqlite(db) if r["run_id"] in _ALPHA]
    monkeypatch.setattr(queries, "_RUN_ID_CHUNK", 1)
    assert api.read_drift_columns_sqlite(db, run_ids=requested) == expected_cols
    assert api.read_drift_distributions_sqlite(db, run_ids=requested) == expected_dist


# --- CLI surfaces -------------------------------------------------------------


@pytest.mark.parametrize(("kwargs", "eligible"), _CASES)
def test_cli_report_scopes_columns_and_distributions(
    monkeypatch, tmp_path, capsys, kwargs, eligible
):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = _build_db(tmp_path)
    out = tmp_path / "report.md"
    argv = ["drift-history", "report", "--db", str(db), "--output", str(out)]
    rc = cli.main([*argv, *_cli_filter_args(kwargs), "--include-columns", "--include-plots"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    _assert_scoped_text(text, eligible)
    if not eligible:
        assert "_No column-level drift rows available._" in text
        assert "_No distribution rows available._" in text


@pytest.mark.parametrize(("kwargs", "eligible"), _CASES)
def test_cli_dashboard_scopes_columns_and_distributions(
    monkeypatch, tmp_path, capsys, kwargs, eligible
):
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = _build_db(tmp_path)
    out = tmp_path / "dashboard.html"
    argv = ["drift-history", "dashboard", "--db", str(db), "--output", str(out)]
    rc = cli.main([*argv, *_cli_filter_args(kwargs), "--include-plots"])
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    _assert_scoped_text(text, eligible)
    expected_rows = sum(1 for c in _COLUMNS if c[0] in eligible)
    assert f"  - Column rows: {expected_rows}" in capsys.readouterr().err
    if not eligible:
        assert "No column-level drift rows available." in text
        assert "No distribution rows available." in text


def test_cli_export_xlsx_scopes_sheets(monkeypatch, tmp_path, capsys):
    openpyxl = pytest.importorskip("openpyxl")
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = _build_db(tmp_path)
    out = tmp_path / "drift.xlsx"
    rc = cli.main(
        [
            "drift-history",
            "export-xlsx",
            "--db",
            str(db),
            "--out",
            str(out),
            "--current-dataset-id",
            "ds_beta",
            "--include-distributions",
        ]
    )
    assert rc == 0
    columns = _sheet_records(openpyxl, out, "columns")
    distributions = _sheet_records(openpyxl, out, "distributions")
    assert {r["run_id"] for r in columns} == _BETA
    assert {r["run_id"] for r in distributions} == _BETA


def test_cli_plot_scopes_column_charts(monkeypatch, tmp_path, capsys):
    pytest.importorskip("matplotlib")
    monkeypatch.setattr(cli, "setup_logging", lambda **_: None)
    db = _build_db(tmp_path)
    argv = ["drift-history", "plot", "--db", str(db), "--out", str(tmp_path / "plots")]
    rc = cli.main([*argv, "--chart", "psi-by-column", "--current-dataset-id", "ds_beta"])
    assert rc == 0
    err = capsys.readouterr().err
    assert f"  - psi-by-column points: {len(_column_names(_BETA))}" in err


# --- Report / dashboard builders ----------------------------------------------


@pytest.mark.parametrize(("kwargs", "eligible"), _CASES)
def test_report_builder_scopes_columns_and_distributions(tmp_path, kwargs, eligible):
    db = _build_db(tmp_path)
    text = build_drift_history_report(
        db, fmt="html", include_columns=True, include_plots=True, **kwargs
    )
    _assert_scoped_text(text, eligible)
    if not eligible:
        assert "<p>No column-level drift rows available.</p>" in text
        assert "<p>No distribution rows available.</p>" in text


@pytest.mark.parametrize(("kwargs", "eligible"), _CASES)
def test_api_dashboard_scopes_columns_and_distributions(tmp_path, kwargs, eligible):
    db = _build_db(tmp_path)
    text = api.drift_dashboard(db, include_plots=True, **kwargs)
    _assert_scoped_text(text, eligible)
    if not eligible:
        assert "No column-level drift rows available." in text
        assert "No drifted columns detected." in text
        assert "No distribution rows available." in text


# --- XLSX exporter ------------------------------------------------------------


def _sheet_records(openpyxl: Any, path: Path, name: str) -> list[dict[str, Any]]:
    # Normal (not read-only) mode keeps trailing empty cells, so rows match the header.
    wb = openpyxl.load_workbook(path)
    try:
        rows = list(wb[name].iter_rows(values_only=True))
    finally:
        wb.close()
    header, *data = rows
    return [dict(zip(header, row, strict=True)) for row in data]


@pytest.mark.parametrize(("kwargs", "eligible"), _CASES)
def test_xlsx_export_scopes_columns_and_distributions(tmp_path, kwargs, eligible):
    openpyxl = pytest.importorskip("openpyxl")
    db = _build_db(tmp_path)
    out = tmp_path / "drift.xlsx"
    result = api.export_drift_history_xlsx(db, out, include_distributions=True, **kwargs)

    runs = _sheet_records(openpyxl, out, "runs")
    columns = _sheet_records(openpyxl, out, "columns")
    distributions = _sheet_records(openpyxl, out, "distributions")
    assert {r["run_id"] for r in runs} == eligible
    assert {r["run_id"] for r in columns} == eligible
    assert {r["run_id"] for r in distributions} == eligible
    assert {r["column_name"] for r in columns} == _column_names(eligible)
    assert {r["psi"] for r in columns if r["column_name"] == "shared_col"} == _shared_psi(eligible)
    assert result["row_counts"]["columns"] == sum(1 for c in _COLUMNS if c[0] in eligible)
    assert result["row_counts"]["distributions"] == sum(
        1 for d in _DISTRIBUTIONS if d[0] in eligible
    )


# --- PNG plot exporter --------------------------------------------------------


@pytest.mark.parametrize("chart", ["all", "psi-by-column"])
@pytest.mark.parametrize(("kwargs", "eligible"), _CASES)
def test_plot_export_scopes_column_charts(tmp_path, monkeypatch, chart, kwargs, eligible):
    pytest.importorskip("matplotlib")
    from data_quality_toolkit.adapters.exporters.viz import drift_plots

    models: list[dict[str, dict[str, Any]]] = []
    real_build = drift_plots.build_plot_model

    def recording_build(**data: Any) -> dict[str, dict[str, Any]]:
        model = real_build(**data)
        models.append(model)
        return model

    monkeypatch.setattr(drift_plots, "build_plot_model", recording_build)
    db = _build_db(tmp_path)
    result = api.export_drift_plots(db, tmp_path / "plots", chart=chart, **kwargs)

    psi_chart = models[0]["psi-by-column"]
    assert set(psi_chart["labels"]) == _column_names(eligible)
    assert result["row_counts"]["psi-by-column"] == len(_column_names(eligible))
    shared = _shared_psi(eligible)
    if shared:
        mean = psi_chart["values"][psi_chart["labels"].index("shared_col")]
        assert mean == pytest.approx(sum(shared) / len(shared))
    top = models[0]["top-drifted"]
    assert set(top["labels"]) == _column_names(eligible, drifted_only=True)
    if chart == "all":
        assert result["row_counts"]["top-drifted"] == len(
            _column_names(eligible, drifted_only=True)
        )
