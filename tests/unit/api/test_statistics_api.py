from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def _statistics_csv(tmp_path: Path) -> Path:
    csv = tmp_path / "stats.csv"
    csv.write_text(
        "variant,score,converted\nA,10,1\nA,12,1\nB,20,0\nB,22,1\n",
        encoding="utf-8",
    )
    return csv


def test_statistics_public_exports_are_minimal() -> None:
    import data_quality_toolkit.api as api

    exported = set(api.__all__)
    assert {
        "stats_profile_csv",
        "select_statistical_test",
        "run_statistical_test",
        "compare_ab",
    } <= exported
    assert {
        "numeric_summary",
        "quick_profile",
        "correlation_matrix",
        "normal_cdf",
        "ci_mean",
        "bootstrap_ci",
        "power_mean",
        "cohen_d",
    }.isdisjoint(exported)


def test_statistics_api_root_exports_work() -> None:
    from data_quality_toolkit import (
        compare_ab,
        run_statistical_test,
        select_statistical_test,
        stats_profile_csv,
    )

    assert callable(stats_profile_csv)
    assert callable(select_statistical_test)
    assert callable(run_statistical_test)
    assert callable(compare_ab)


def test_stats_profile_csv_profiles_small_csv(tmp_path: Path) -> None:
    from data_quality_toolkit import stats_profile_csv

    result = stats_profile_csv(_statistics_csv(tmp_path), columns=["variant", "score"])

    assert result["status"] == "ok"
    assert result["columns"] == ["variant", "score"]
    assert result["profile"]["n_rows"] == 4
    assert result["profile"]["n_columns"] == 2
    assert result["profile"]["missing"] == {}
    assert result["numeric_summary"][0]["column"] == "score"
    assert result["numeric_summary"][0]["mean"] == 16.0


def test_stats_profile_csv_invalid_path_returns_structured_status(tmp_path: Path) -> None:
    from data_quality_toolkit import stats_profile_csv

    result = stats_profile_csv(tmp_path / "missing.csv")

    assert result["status"] == "invalid_input"
    assert "reason" in result
    assert result["path"].endswith("missing.csv")


def test_select_statistical_test_maps_representative_keys() -> None:
    from data_quality_toolkit import select_statistical_test

    numeric = select_statistical_test(
        "numeric",
        "two_independent",
        sigma_known=False,
        equal_variance_assumed=False,
    )
    proportion = select_statistical_test("proportion", "two_independent")

    assert numeric["status"] == "ok"
    assert numeric["test_key"] == "TWO_T_WELCH"
    assert proportion["status"] == "ok"
    assert proportion["test_key"] == "TWO_PROP_Z"


def test_run_statistical_test_returns_expected_one_sample_t_result() -> None:
    pytest.importorskip("scipy")

    from data_quality_toolkit import run_statistical_test

    result = run_statistical_test("ONE_T", sample=[1.0, 2.0, 3.0, 4.0, 5.0], null_mean=3.0)

    assert result["status"] == "ok"
    assert result["test_key"] == "ONE_T"
    assert result["statistic"] == pytest.approx(0.0)
    assert result["p_value"] == pytest.approx(1.0)
    assert result["reject_null"] is False


def test_compare_ab_numeric_works() -> None:
    pytest.importorskip("scipy")

    from data_quality_toolkit import compare_ab

    result = compare_ab(
        [20.0, 22.0, 24.0, 26.0, 28.0],
        [1.0, 2.0, 2.0, 3.0, 4.0],
        variable_type="numeric",
        alternative="greater",
    )

    assert result["status"] == "ok"
    assert result["test_key"] == "TWO_T_WELCH"
    assert result["selection"]["test_key"] == "TWO_T_WELCH"
    p_value = result["p_value"]
    assert p_value is not None
    assert p_value < 0.01


def test_compare_ab_proportion_works() -> None:
    pytest.importorskip("scipy")

    from data_quality_toolkit import compare_ab

    result = compare_ab(
        variable_type="proportion",
        successes_a=70,
        n_a=100,
        successes_b=50,
        n_b=100,
        alternative="greater",
    )

    assert result["status"] == "ok"
    assert result["test_key"] == "TWO_PROP_Z"
    assert result["reject_null"] is True


def test_run_statistical_test_missing_scipy_returns_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit import run_statistical_test
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)

    result = run_statistical_test("ONE_T", sample=[1.0, 2.0, 3.0])

    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    assert result["statistic"] is None
    assert result["p_value"] is None


def test_compare_ab_missing_scipy_returns_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit import compare_ab
    from data_quality_toolkit.domain.statistics import ab

    monkeypatch.setattr(ab._inference, "import_scipy_stats", lambda: None)

    result = compare_ab(
        [3.0, 4.0, 5.0],
        [1.0, 2.0, 3.0],
        variable_type="numeric",
        alternative="greater",
    )

    assert result["status"] == "unavailable"
    assert result["selection"]["test_key"] == "TWO_T_WELCH"
    assert result["scipy_available"] is False


# ── chi-square diagnostics reach the public API from the backend result ───────


def test_run_statistical_test_exposes_backend_expected_count_diagnostics() -> None:
    pytest.importorskip("scipy")
    from data_quality_toolkit import run_statistical_test

    result = run_statistical_test("CHI_IND", table=[[1, 0], [0, 99]])

    assert result["status"] == "ok"
    assert "below 1" in " ".join(result["warnings"]).lower()
    diagnostics = result["assumptions"]["expected_counts"]
    assert diagnostics["any_below_1"] is True
    assert diagnostics["sparse"] is True


def test_run_statistical_test_diagnostics_match_the_domain_engine() -> None:
    pytest.importorskip("scipy")
    from data_quality_toolkit import run_statistical_test
    from data_quality_toolkit.domain.statistics import inference

    cases: list[tuple[str, dict[str, Any]]] = [
        ("CHI_GOF", {"observed": [1, 1, 0, 1]}),
        ("CHI_IND", {"table": [[5, 5], [5, 25]]}),
        ("CHI_HOMOG", {"table": [[1, 0], [0, 99]]}),
    ]
    for key, kwargs in cases:
        public = run_statistical_test(key, **kwargs)
        domain = inference.calculate_p_value(key, **kwargs)
        # The API adds no statistical rule of its own: same warnings, same diagnostics.
        assert public["warnings"] == domain["warnings"]
        assert public["messages"] == domain["messages"]
        assert public["assumptions"] == domain["assumptions"]


def test_run_statistical_test_healthy_chi_square_has_no_false_warning() -> None:
    pytest.importorskip("scipy")
    from data_quality_toolkit import run_statistical_test

    result = run_statistical_test("CHI_HOMOG", table=[[25, 25], [25, 25]])

    assert result["warnings"] == []
    assert result["assumptions"]["expected_counts"]["sparse"] is False


def test_run_statistical_test_discloses_2x2_continuity_correction() -> None:
    pytest.importorskip("scipy")
    from data_quality_toolkit import run_statistical_test

    result = run_statistical_test("CHI_IND", table=[[10, 20], [30, 40]])

    assert result["assumptions"]["continuity_correction"] is True
    assert "continuity correction" in " ".join(result["messages"]).lower()


def test_existing_statistical_result_keys_are_unchanged() -> None:
    pytest.importorskip("scipy")
    from data_quality_toolkit import run_statistical_test

    result = run_statistical_test("CHI_IND", table=[[30, 10], [10, 30]])

    # Additive only: every previously published key still exists with its meaning.
    assert {
        "status",
        "test_key",
        "statistic",
        "p_value",
        "alpha",
        "reject_null",
        "method",
        "reason",
        "alternative",
        "warnings",
        "messages",
        "assumptions",
        "scipy_available",
    } <= set(result)
    assert {"rows", "columns", "dof"} <= set(result["assumptions"])
