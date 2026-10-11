"""Unit tests for the Streamlit-free monitoring UI service (v2.6.0).

The service (``adapters.ui.services.monitoring``) is a thin ``(data, err)``
wrapper over the shared view-model. These tests monkeypatch the view-model
builders so no real database is required, and assert the service stays free of
Streamlit and direct storage-adapter imports.
"""

from __future__ import annotations

import ast
import inspect
from typing import cast

import data_quality_toolkit.adapters.ui.services.monitoring as svc
from data_quality_toolkit.application.monitoring.view_model import (
    ColumnDrift,
    DistributionBin,
    MonitoringOverview,
    RunDetail,
    RunRow,
    TrendSummary,
)


def _make_overview() -> MonitoringOverview:
    summary = TrendSummary(
        total_runs=2,
        drifted_runs=1,
        non_drifted_runs=1,
        drift_rate=0.5,
        latest_run_id="r2",
        latest_created_at="2026-06-13T00:00:02+00:00",
        latest_drift_detected=True,
        columns_tested_total=8,
        columns_tested_average=4.0,
        columns_drifted_total=2,
        columns_drifted_average=1.0,
    )
    run = RunRow(
        run_id="r2",
        created_at="2026-06-13T00:00:02+00:00",
        current_dataset_id="cd1",
        status="ok",
        drift_detected=True,
        columns_tested=4,
        columns_drifted=2,
        columns_skipped=0,
    )
    return MonitoringOverview(
        summary=summary,
        runs=[run],
        db_path="x.db",
        current_dataset_id=None,
        limit=None,
        generated_at="2026-06-13T00:00:09+00:00",
    )


def _make_column() -> ColumnDrift:
    return ColumnDrift(
        column_name="amount",
        kind="numeric",
        test="ks",
        drift_detected=True,
        statistic=0.4,
        p_value=0.01,
        psi=0.27,
        js_distance=0.18,
        wasserstein=3.5,
        reference_n=100,
        current_n=120,
        status="ok",
        skip_reason=None,
    )


def _make_bin() -> DistributionBin:
    return DistributionBin(
        column_name="amount",
        kind="numeric",
        bin_index=0,
        bin_label="[0, 10)",
        reference_prob=0.5,
        current_prob=0.3,
    )


# --- load_monitoring_overview ------------------------------------------------


def test_load_overview_blank_path_returns_clean_error():
    data, err = svc.load_monitoring_overview("   ")
    assert data is None
    assert err and "No database path" in err


def test_load_overview_missing_file_returns_clean_error(tmp_path):
    missing = tmp_path / "nope.db"
    data, err = svc.load_monitoring_overview(str(missing))
    assert data is None
    assert err and "not found" in err.lower()


def test_load_overview_success(monkeypatch, tmp_path):
    db = tmp_path / "mon.db"
    db.write_text("")  # exists so the path guard passes
    overview = _make_overview()
    monkeypatch.setattr(svc, "build_monitoring_overview", lambda *a, **k: overview)
    data, err = svc.load_monitoring_overview(str(db))
    assert err is None
    assert data is overview


def test_load_overview_unexpected_error_returns_message(monkeypatch, tmp_path):
    db = tmp_path / "mon.db"
    db.write_text("")

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(svc, "build_monitoring_overview", boom)
    data, err = svc.load_monitoring_overview(str(db))
    assert data is None
    assert err and "kaboom" in err


def test_load_overview_error_redacts_full_db_path(monkeypatch, tmp_path):
    db = tmp_path / "synthetic-monitoring.db"
    db.write_text("")

    def boom(*a, **k):
        raise RuntimeError(f"Could not inspect {db}")

    monkeypatch.setattr(svc, "build_monitoring_overview", boom)
    data, err = svc.load_monitoring_overview(str(db))
    assert data is None
    assert err and db.name in err
    assert str(db.parent) not in err


# --- load_run_detail ----------------------------------------------------------


def test_load_run_detail_success(monkeypatch, tmp_path):
    db = tmp_path / "mon.db"
    db.write_text("")
    detail = RunDetail(run=_make_overview().runs[0], columns=[_make_column()], distributions=[])
    monkeypatch.setattr(svc, "build_run_detail", lambda *a, **k: detail)
    data, err = svc.load_run_detail(str(db), "r2")
    assert err is None
    assert data is detail


def test_load_run_detail_blank_run_id_error(tmp_path):
    db = tmp_path / "mon.db"
    db.write_text("")
    data, err = svc.load_run_detail(str(db), "  ")
    assert data is None
    assert err and "run_id" in err


def test_load_run_detail_missing_db_error(tmp_path):
    data, err = svc.load_run_detail(str(tmp_path / "nope.db"), "r2")
    assert data is None
    assert err


# --- load_distribution_series ------------------------------------------------


def test_load_distribution_series_success(monkeypatch, tmp_path):
    db = tmp_path / "mon.db"
    db.write_text("")
    bins = [_make_bin()]
    monkeypatch.setattr(svc, "build_distribution_series", lambda *a, **k: bins)
    data, err = svc.load_distribution_series(str(db), "r2", "amount")
    assert err is None
    assert data == bins


def test_load_distribution_series_requires_run_and_column(tmp_path):
    db = tmp_path / "mon.db"
    db.write_text("")
    data, err = svc.load_distribution_series(str(db), "r2", "  ")
    assert data is None
    assert err and "required" in err.lower()


def test_load_distribution_series_error_path(monkeypatch, tmp_path):
    db = tmp_path / "mon.db"
    db.write_text("")

    def boom(*a, **k):
        raise ValueError("bad column")

    monkeypatch.setattr(svc, "build_distribution_series", boom)
    data, err = svc.load_distribution_series(str(db), "r2", "amount")
    assert data is None
    assert err and "bad column" in err


# --- converters return plain dict/list structures ----------------------------


def test_converters_return_plain_structures():
    overview = _make_overview()
    assert isinstance(svc.overview_to_dict(overview), dict)
    runs = svc.runs_to_dicts(overview)
    assert isinstance(runs, list) and isinstance(runs[0], dict)
    cols = svc.columns_to_dicts([_make_column()])
    assert isinstance(cols, list) and cols[0]["psi"] == 0.27
    dists = svc.distributions_to_dicts([_make_bin()])
    assert isinstance(dists, list) and dists[0]["bin_index"] == 0


# --- privacy / formatting helpers --------------------------------------------


def test_redact_path_to_basename_strips_directories():
    assert svc.redact_path_to_basename("/secret/dir/monitoring.db") == "monitoring.db"
    assert svc.redact_path_to_basename("C:\\\\users\\\\x\\\\mon.db").endswith("mon.db")


def test_redact_path_to_basename_exact_windows():
    # Host-independent: Windows separators stripped even on a POSIX runner.
    assert (
        svc.redact_path_to_basename("C:\\Users\\redacted\\secret\\drift.duckdb") == "drift.duckdb"
    )


def test_redact_path_to_basename_exact_posix():
    assert svc.redact_path_to_basename("/home/redacted/secret/drift.duckdb") == "drift.duckdb"


def test_redact_path_to_basename_exact_relative():
    assert svc.redact_path_to_basename("relative/path/report.json") == "report.json"


def test_redact_path_to_basename_exact_plain():
    assert svc.redact_path_to_basename("plain.csv") == "plain.csv"


def test_redact_path_to_basename_blank_or_none():
    assert svc.redact_path_to_basename(None) == ""
    assert svc.redact_path_to_basename("   ") == ""


def test_format_probability_missing_stays_unavailable_not_zero():
    out = svc.format_probability(None)
    assert out == "unavailable"
    assert "0" not in out


def test_format_probability_present_value():
    assert svc.format_probability(0.5) == "0.5000"


# --- bounded drift StoryLens card builder ------------------------------------


def test_drift_cards_at_most_two_and_no_db_path():
    overview = _make_overview()  # total_runs=2, drift present
    cards = svc.build_drift_storylens_cards(
        overview, threshold_metric="drift_rate", threshold_value=0.4
    )
    assert 1 <= len(cards) <= 2
    blob = " ".join(
        " ".join(c.evidence) + c.title + c.summary + c.recommended_action + c.limitations
        for c in cards
    )
    assert overview.db_path not in blob
    assert "x.db" not in blob


def test_drift_cards_insufficient_history_when_few_runs():
    overview = _make_overview()
    object.__setattr__(overview.summary, "total_runs", 1)
    cards = svc.build_drift_storylens_cards(overview)
    assert cards
    assert "drift trend" in cards[0].title.lower()


def test_drift_cards_one_run_drifted_does_not_fabricate_zero():
    # Single drifted run: drifted_runs must reflect the authoritative summary
    # count (1), never a fabricated 0.
    overview = _make_overview()
    object.__setattr__(overview.summary, "total_runs", 1)
    object.__setattr__(overview.summary, "drifted_runs", 1)
    cards = svc.build_drift_storylens_cards(overview)
    evidence = " ".join(cards[0].evidence)
    assert "drifted_runs=0" not in evidence
    assert "drifted_runs=1" in evidence


def test_drift_cards_psi_metric_requires_authoritative_value():
    # psi must not silently bind to summary.drift_rate: no value -> no second card.
    overview = _make_overview()  # total_runs=2 -> card 1 is run status
    no_psi = svc.build_drift_storylens_cards(overview, threshold_metric="psi", threshold_value=0.2)
    assert len(no_psi) == 1  # only the run-status card, no mislabeled psi card

    with_psi = svc.build_drift_storylens_cards(
        overview, threshold_metric="psi", threshold_value=0.2, threshold_metric_value=0.3
    )
    assert len(with_psi) == 2
    psi_card = with_psi[1]
    assert "psi=0.3000" in psi_card.evidence
    assert "breached=True" in psi_card.evidence  # 0.3 > 0.2


def test_drift_cards_unknown_latest_status_not_no_drift():
    overview = _make_overview()
    object.__setattr__(overview.summary, "latest_drift_detected", None)
    cards = svc.build_drift_storylens_cards(overview)
    card = cards[0]
    assert "unknown" in card.title.lower()
    assert "drift_detected=unknown" in card.evidence
    # Must not be a no-drift reassurance.
    assert "no drift" not in card.title.lower()
    assert card.severity == "info"


def test_drift_cards_empty_on_malformed_input():
    assert svc.build_drift_storylens_cards(cast(MonitoringOverview, None)) == []


# --- boundary (static source inspection) -------------------------------------


def _imported_modules(module) -> set[str]:
    """Return the set of module names referenced by import statements (AST-based)."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_service_does_not_import_streamlit():
    assert not any(m.split(".")[0] == "streamlit" for m in _imported_modules(svc))


def test_service_does_not_import_storage_adapters_directly():
    assert not any("adapters.storage" in m for m in _imported_modules(svc))


def test_service_imports_monitoring_builders_via_api():
    """Monitoring view-model symbols sourced from public api, not application layer directly."""
    modules = _imported_modules(svc)
    assert not any(
        "application.monitoring.view_model" in m for m in modules
    ), "monitoring service must import view-model symbols via api"


# --- Drift Explorer error surface consumes the shared redaction policy ---
#
# Every path/secret literal below is a synthetic sentinel. Before this fix this
# surface replaced only the *selected* DB path by hand, so any other absolute
# path the exception carried (a journal/WAL sidecar, a temp directory, a chained
# OSError filename) reached the UI verbatim. These tests pin the fix.

SYNTHETIC_SENTINEL_SECRET = "DQT_TEST_SECRET_ABC123XYZ"  # noqa: S105 - synthetic fixture


def test_error_redacts_an_unrelated_windows_path(monkeypatch, tmp_path):
    db = tmp_path / "monitoring.db"
    db.write_text("")
    sidecar = "C:\\Users\\SensitiveUser\\private\\other.db-journal"

    def boom(*a, **k):
        raise RuntimeError(f"unable to open database file: {sidecar}")

    monkeypatch.setattr(svc, "build_monitoring_overview", boom)
    data, err = svc.load_monitoring_overview(str(db))
    assert data is None
    assert err == "unable to open database file: other.db-journal"
    assert "SensitiveUser" not in err
    assert "private" not in err
    assert "C:" not in err


def test_error_redacts_an_unrelated_posix_path(monkeypatch, tmp_path):
    db = tmp_path / "monitoring.db"
    db.write_text("")

    def boom(*a, **k):
        raise OSError(f"locked: /home/sensitive-user/{SYNTHETIC_SENTINEL_SECRET}/mon.db-wal")

    monkeypatch.setattr(svc, "build_run_detail", boom)
    data, err = svc.load_run_detail(str(db), "r2")
    assert data is None
    assert err == "locked: mon.db-wal"
    assert SYNTHETIC_SENTINEL_SECRET not in err
    assert "sensitive-user" not in err


def test_error_redacts_paths_on_the_distribution_surface(monkeypatch, tmp_path):
    db = tmp_path / "monitoring.db"
    db.write_text("")

    def boom(*a, **k):
        raise ValueError("bad column in C:\\Users\\SensitiveUser\\private\\schema.sql")

    monkeypatch.setattr(svc, "build_distribution_series", boom)
    data, err = svc.load_distribution_series(str(db), "r2", "amount")
    assert data is None
    assert err == "bad column in schema.sql"
    assert "SensitiveUser" not in err


def test_relative_db_path_barrier_is_retained(monkeypatch, tmp_path):
    """Defense in depth: the shared policy only matches *absolute* paths.

    A relative DB path is still replaced by the caller-side barrier, so removing
    that barrier in favour of the shared helper alone would be a regression.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sub").mkdir()
    rel = "sub/monitoring.db"
    (tmp_path / rel).write_text("")

    def boom(*a, **k):
        raise RuntimeError(f"could not inspect {rel}")

    monkeypatch.setattr(svc, "build_monitoring_overview", boom)
    data, err = svc.load_monitoring_overview(rel)
    assert data is None
    assert err == "could not inspect monitoring.db"
    assert "sub/" not in err


def test_error_message_is_deterministic_and_idempotent(monkeypatch, tmp_path):
    db = tmp_path / "monitoring.db"
    db.write_text("")

    def boom(*a, **k):
        raise RuntimeError("unable to open C:\\Users\\SensitiveUser\\private\\other.db")

    monkeypatch.setattr(svc, "build_monitoring_overview", boom)
    first = svc.load_monitoring_overview(str(db))[1]
    second = svc.load_monitoring_overview(str(db))[1]
    assert first == second
    # Re-scrubbing an already-safe message changes nothing.
    assert svc.redact_message_paths(first) == first


def test_error_surface_preserves_the_structured_code_and_type(monkeypatch, tmp_path):
    """Redaction scrubs the message text only; the error contract is untouched."""
    db = tmp_path / "monitoring.db"
    db.write_text("")
    exc = FileNotFoundError(2, "No such file", "C:\\Users\\SensitiveUser\\private\\other.db")
    info = svc.to_error_info(exc)
    assert info["code"] == "FILE_NOT_FOUND"
    assert info["exc_type"] == "FileNotFoundError"

    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(svc, "build_monitoring_overview", boom)
    data, err = svc.load_monitoring_overview(str(db))
    assert data is None
    # (result, err) tuple shape unchanged; err stays a plain safe string.
    assert isinstance(err, str)
    assert "other.db" in err
    assert "SensitiveUser" not in err


def test_service_does_not_define_its_own_basename_redactor():
    """The value-form rule must be imported, never restated here."""
    from data_quality_toolkit.shared.text_redaction import redact_path_to_basename as shared

    assert svc.redact_path_to_basename is shared
    tree = ast.parse(inspect.getsource(svc))
    local_defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "redact_path_to_basename" not in local_defs
