"""Contract tests for the st-free UI service modules (UI restructure).

Pins the two structural rules of adapters/ui/services:
1. No module-level or nested streamlit import — services stay UI-framework-free.
2. Every wrapper keeps the ``(result, err)`` tuple contract: errors come back
   as ``(None, message)``, never as raised exceptions.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.components.downloads import (
    csv_download_button,
    json_download_button,
)
from data_quality_toolkit.adapters.ui.services import (
    artifacts,
    assessment,
    compare,
    diagnostics,
    export,
    kpi,
    pipeline,
    preprocessing,
    statistics,
)
from data_quality_toolkit.adapters.ui.services.assessment import (
    _load_profile_chunked,
    _load_run_history,
    _run_assess_csv,
)
from data_quality_toolkit.adapters.ui.services.compare import _run_compare
from data_quality_toolkit.adapters.ui.services.diagnostics import (
    collect_ai_availability,
    collect_capability_snapshot,
    collect_thresholds,
    collect_versions,
    privacy_posture,
    probe_writable_dir,
)
from data_quality_toolkit.adapters.ui.services.export import _export_csv_to_dir
from data_quality_toolkit.adapters.ui.services.kpi import (
    _generate_dim_time_csv,
    _kpi_emit_to_bytes,
    _kpi_graph_to_str,
    _run_kpi_validate,
)
from data_quality_toolkit.adapters.ui.services.pipeline import (
    _load_pipeline_config_file,
    _run_elt_pipeline,
)


class FakeDownloadSt:
    """Tiny Streamlit recorder for download-button helper tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def download_button(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


# ── download components ──────────────────────────────────────────────────────


def test_csv_download_helper_serializes_dataframe_without_index() -> None:
    st = FakeDownloadSt()
    df = pd.DataFrame({"name": ["alpha", "beta"], "value": [1, 2]})

    csv_download_button(st, "Download table", df, "table.csv")

    args, kwargs = st.calls[0]
    assert args == ("Download table",)
    assert kwargs["file_name"] == "table.csv"
    assert kwargs["mime"] == "text/csv"
    assert kwargs["data"].splitlines() == ["name,value", "alpha,1", "beta,2"]


def test_json_download_helper_serializes_structured_payload() -> None:
    st = FakeDownloadSt()

    json_download_button(st, "Download JSON", {"path": Path("artifact.json")}, "artifact.json")

    args, kwargs = st.calls[0]
    assert args == ("Download JSON",)
    assert kwargs["file_name"] == "artifact.json"
    assert kwargs["mime"] == "application/json"
    assert json.loads(kwargs["data"]) == {"path": "artifact.json"}


# ── structural rule: services must not import streamlit ──────────────────────


@pytest.mark.parametrize(
    "module",
    [
        artifacts,
        assessment,
        compare,
        export,
        kpi,
        pipeline,
        diagnostics,
        preprocessing,
        statistics,
    ],
)
def test_service_module_does_not_import_streamlit(module: object) -> None:
    src = inspect.getsource(module)  # type: ignore[arg-type]
    assert "import streamlit" not in src, f"{module} must stay streamlit-free"


# ── (result, err) tuple contract: error paths never raise ────────────────────


def test_run_assess_csv_error_returns_tuple() -> None:
    with patch(
        "data_quality_toolkit.adapters.ui.services.assessment._assess_csv",
        side_effect=RuntimeError("boom"),
    ):
        out, err = _run_assess_csv("data.csv")
    assert out is None
    assert err is not None
    assert "boom" in err


def test_run_assess_csv_success_passes_through() -> None:
    fake = {"profile": {"rows": 1}, "assessment": {"score": 1.0, "issues": []}}
    with patch(
        "data_quality_toolkit.adapters.ui.services.assessment._assess_csv",
        return_value=fake,
    ) as mock:
        out, err = _run_assess_csv("  data.csv  ")
    assert err is None
    assert out == fake
    mock.assert_called_once_with("data.csv")


def test_load_profile_chunked_error_returns_tuple() -> None:
    with patch(
        "data_quality_toolkit.api.profile_csv",
        side_effect=FileNotFoundError("missing.csv not found"),
    ):
        envelope, err = _load_profile_chunked("missing.csv", chunksize=1000)
    assert envelope is None
    assert err is not None
    assert "not found" in err


def test_load_run_history_missing_db_returns_empty(tmp_path: Path) -> None:
    records, err = _load_run_history(str(tmp_path / "nope.db"), "ds1")
    assert records == []
    assert err is None


def test_export_csv_to_dir_relative_outdir_returns_error() -> None:
    result, err = _export_csv_to_dir("/data/test.csv", "relative/path")
    assert result is None
    assert err is not None


def test_export_csv_to_dir_exposes_quality_db_result(tmp_path: Path) -> None:
    expected = {
        "export_paths": {"quality_db": str(tmp_path / "dqt.db")},
        "quality_db_path": str(tmp_path / "dqt.db"),
        "quality_db_status": "persisted",
        "quality_db_error": None,
    }
    with patch("data_quality_toolkit.api.export_csv", return_value=expected) as mock_export:
        result, err = _export_csv_to_dir(str(tmp_path / "input.csv"), str(tmp_path))

    assert err is None
    assert result == expected
    mock_export.assert_called_once()


def test_run_kpi_validate_missing_file_returns_error() -> None:
    result, err = _run_kpi_validate("nonexistent/catalog.yaml")
    assert result is None
    assert err is not None


def test_generate_dim_time_csv_bad_dates_returns_error() -> None:
    csv_str, row_count, err = _generate_dim_time_csv("not-a-date", "also-bad")
    assert csv_str is None
    assert row_count is None
    assert err is not None


def test_generate_dim_time_csv_happy_path() -> None:
    csv_str, row_count, err = _generate_dim_time_csv("2024-01-01", "2024-01-05")
    assert err is None
    assert row_count == 5
    assert csv_str


def test_kpi_emit_to_bytes_missing_catalog_returns_error() -> None:
    dax_bytes, tmsl_bytes, err = _kpi_emit_to_bytes("nonexistent/catalog.yaml")
    assert dax_bytes is None
    assert tmsl_bytes is None
    assert err is not None


def test_kpi_graph_to_str_missing_catalog_returns_error() -> None:
    content, err = _kpi_graph_to_str("nonexistent/catalog.yaml")
    assert content is None
    assert err is not None


def test_run_elt_pipeline_success() -> None:
    with patch("data_quality_toolkit.api.create_elt_pipeline") as mock_create:
        mock_pipeline = mock_create.return_value
        from dataclasses import dataclass

        @dataclass
        class ELTResult:
            run_id: str
            status: str
            steps: list
            manifest: Any = None

        mock_pipeline.run.return_value = ELTResult("1", "success", [])

        out, err = _run_elt_pipeline("1", ".")
        assert out is not None
        assert err is None
        assert out["run_id"] == "1"


def test_run_elt_pipeline_error() -> None:
    with patch("data_quality_toolkit.api.create_elt_pipeline", side_effect=Exception("boom")):
        out, err = _run_elt_pipeline("1", ".")
    assert out is None
    assert err == "boom"


def test_load_pipeline_config_file_success() -> None:
    with patch("data_quality_toolkit.shared.config.load_pipeline_config", return_value={"a": 1}):
        out, err = _load_pipeline_config_file("config.yaml")
    assert out == {"a": 1}
    assert err is None


def test_collect_versions_reports_real_package_version() -> None:
    versions = collect_versions()
    assert versions["data_quality_toolkit"]
    # The rebuilt diagnostics must not emit the old placeholder value.
    assert versions["data_quality_toolkit"] != "0.1.0"
    assert "python" in versions


def test_capability_snapshot_reports_known_optionals() -> None:
    snapshot = collect_capability_snapshot()
    assert "streamlit" in snapshot
    assert "scipy" in snapshot
    assert set(snapshot.values()) <= {"available", "not installed"}
    # AI/model packages must never be probed/reported here.
    for banned in ("torch", "transformers", "huggingface_hub"):
        assert banned not in snapshot


def test_ai_availability_is_default_off_and_path_free() -> None:
    ai = collect_ai_availability()
    assert ai["enabled"] is False
    assert ai["default"] == "off"
    # Reason must not leak env-var names or model paths.
    assert "DQT_STORYLENS" not in ai["reason"]


def test_thresholds_expose_deterministic_values() -> None:
    thresholds = collect_thresholds()
    assert thresholds["null_threshold"] == 0.2
    assert thresholds["schema_penalty_cap"] == 0.30
    assert "severity_penalties" in thresholds


def test_privacy_posture_is_non_empty() -> None:
    posture = privacy_posture()
    assert posture
    assert "optional_ai" in posture


def test_probe_writable_dir_success(tmp_path: Path) -> None:
    success, err = probe_writable_dir(str(tmp_path))
    assert success is True
    assert err is None


def test_probe_writable_dir_missing() -> None:
    success, err = probe_writable_dir("nonexistent_dir")
    assert success is False
    assert err is not None


# ── statistics distribution service ─────────────────────────────────────────


def test_statistics_distribution_service_computes_continuous_result() -> None:
    pytest.importorskip("scipy")
    result = statistics.theoretical_distribution_result(
        "Normal",
        "PDF",
        x=0.0,
        mu=0.0,
        sigma=1.0,
    )
    assert result["status"] == "ok"
    assert result["distribution"] == "Normal"
    assert result["calculation"] == "PDF"
    assert result["value"] == pytest.approx(0.3989422804, abs=1e-7)


def test_statistics_distribution_service_computes_discrete_result() -> None:
    pytest.importorskip("scipy")
    result = statistics.theoretical_distribution_result(
        "Binomial",
        "PMF",
        k=1,
        n=3,
        p=0.5,
    )
    assert result["status"] == "ok"
    assert result["distribution"] == "Binomial"
    assert result["calculation"] == "PMF"
    assert result["value"] == pytest.approx(0.375)


def test_statistics_distribution_service_computes_two_tail_critical_value() -> None:
    pytest.importorskip("scipy")
    result = statistics.theoretical_distribution_result(
        "Normal",
        "Critical value (two-tail)",
        alpha=0.05,
    )
    assert result["status"] == "ok"
    assert result["method"] == "confidence_level_to_z"
    assert result["tail"] == "two-tail"
    assert result["value"] == pytest.approx(1.9599639845, abs=1e-7)


def test_statistics_distribution_service_invalid_input_is_safe() -> None:
    result = statistics.theoretical_distribution_result(
        "Normal",
        "PDF",
        x=0.0,
        sigma=0.0,
    )
    assert result["status"] == "invalid_input"
    assert "sigma" in str(result["reason"])


def test_statistics_distribution_service_missing_scipy_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(statistics._distributions, "normal_pdf", lambda *_a, **_k: None)
    result = statistics.theoretical_distribution_result("Normal", "PDF", x=0.0)
    assert result["status"] == "unavailable"
    assert "scipy is not installed" in str(result["reason"])


# ── compare service tuple contract ───────────────────────────────────────────

# Underlying workflow function — still valid for deep-patch tests.
_MOCK_COMPARE_WORKFLOW = "data_quality_toolkit.application.workflow.compare.compare_last_two_runs"
# Compare service now routes through api.compare_runs_history.
_MOCK_COMPARE_API = "data_quality_toolkit.api.compare_runs_history"


def test_run_compare_success_returns_result() -> None:
    fake = {"dataset_id": "sha1:abc", "score_delta": 0.1, "issues_delta": -3.0}
    with patch(_MOCK_COMPARE_WORKFLOW, return_value=fake):
        result, err = _run_compare("./dist/dqt.db", "sha1:abc")
    assert err is None
    assert result == fake


def test_run_compare_not_enough_runs_returns_error_message() -> None:
    not_enough = {
        "error": "not_enough_runs",
        "message": "Found 1 run(s) for dataset 'sha1:abc'. Need at least 2.",
        "dataset_id": "sha1:abc",
        "runs_found": 1,
    }
    with patch(_MOCK_COMPARE_WORKFLOW, return_value=not_enough):
        result, err = _run_compare("./dist/dqt.db", "sha1:abc")
    assert result is None
    assert err is not None
    assert "Found 1 run(s)" in err


def test_run_compare_exception_returns_error() -> None:
    with patch(_MOCK_COMPARE_WORKFLOW, side_effect=RuntimeError("boom")):
        result, err = _run_compare("./dist/dqt.db", "sha1:abc")
    assert result is None
    assert err is not None
    assert "boom" in err


def test_run_compare_routes_through_api() -> None:
    """Compare service routes through api.compare_runs_history, not workflow directly."""
    fake = {"dataset_id": "sha1:abc", "score_delta": 0.05}
    with patch(_MOCK_COMPARE_API, return_value=fake) as mock_api:
        result, err = _run_compare("./dist/dqt.db", "sha1:abc")
    assert result == fake
    assert err is None
    mock_api.assert_called_once()
    called_dataset_id, _ = mock_api.call_args.args
    assert called_dataset_id == "sha1:abc"
