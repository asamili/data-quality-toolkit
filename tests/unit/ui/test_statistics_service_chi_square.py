"""Tests for the chi-square service wrappers in the Statistics Lab service.

The service stays streamlit-free and reuses the accepted type-aware, collision-safe
category identity system: native typed values drive grouping, counting, and table
placement while only collision-safe labels are shown. Missing and non-finite (±inf)
values are excluded per row; opaque / control-character / overlong / unresolved-collision
categories are rejected before execution. Computation routes through the public
``run_statistical_test`` seam (``CHI_GOF`` / ``CHI_IND`` / ``CHI_HOMOG``). Chi-square is
right-tail (no one-sided control). Includes non-mocked kernel executions and the
structured scipy-unavailable degradation path.
"""

from __future__ import annotations

import inspect
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import statistics as svc

# ── shared ────────────────────────────────────────────────────────────────────


def test_service_stays_streamlit_free() -> None:
    assert "import streamlit" not in inspect.getsource(svc)


def _gof_options(df: pd.DataFrame, column: str) -> list:
    options, error = svc.chi_square_gof_options(df, column)
    assert error is None
    return options


def _expected_by_label(df: pd.DataFrame, column: str, mapping: dict[str, float]) -> dict:
    """Build an identity-keyed expected-proportion mapping from label→proportion."""
    return {option.identity: mapping[option.label] for option in _gof_options(df, column)}


# ── CHI_GOF: validation ───────────────────────────────────────────────────────


def _gof_df() -> pd.DataFrame:
    return pd.DataFrame({"cat": ["a"] * 30 + ["b"] * 30 + ["c"] * 40})


def test_gof_missing_column_invalid() -> None:
    result = svc.run_chi_square_gof_test(_gof_df(), "nope")
    assert result["status"] == "invalid_input"
    assert result["test_key"] == "CHI_GOF"
    assert "not found" in str(result["reason"])


def test_gof_no_valid_rows_insufficient() -> None:
    df = pd.DataFrame({"cat": [None, np.nan]})
    result = svc.run_chi_square_gof_test(df, "cat")
    assert result["status"] == "insufficient_data"
    assert result["valid_rows"] == 0
    assert result["excluded_rows"] == 2


def test_gof_single_category_rejected() -> None:
    df = pd.DataFrame({"cat": ["a", "a", "a"]})
    result = svc.run_chi_square_gof_test(df, "cat")
    assert result["status"] == "invalid_input"
    assert "at least two distinct" in str(result["reason"])
    assert result["category_count"] == 1


def test_gof_missing_and_non_finite_excluded() -> None:
    df = pd.DataFrame({"cat": ["a", "b", "a", None, np.nan]})
    result = svc.run_chi_square_gof_test(df, "cat")
    assert result["total_rows"] == 5
    assert result["valid_rows"] == 3
    assert result["excluded_rows"] == 2


def test_gof_has_no_one_sided_control() -> None:
    params = inspect.signature(svc.run_chi_square_gof_test).parameters
    assert "alternative" not in params
    result = svc.run_chi_square_gof_test(_gof_df(), "cat")
    # The kernel resolves chi-square as two-sided/right-tail regardless.
    assert result["alternative"] == "two-sided"


# ── CHI_GOF: equal proportions ────────────────────────────────────────────────


def test_gof_equal_proportions_counts_and_order() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_gof_test(_gof_df(), "cat")
    assert result["status"] == "ok"
    assert result["expected_mode"] == "equal"
    assert result["category_count"] == 3
    # Deterministic label order a, b, c.
    assert result["observed_values"] == ["a [str]", "b [str]", "c [str]"]
    assert result["observed_counts"] == [30, 30, 40]
    labels = [entry["category"] for entry in result["categories"]]
    assert labels == ["a [str]", "b [str]", "c [str]"]
    assert [entry["expected_proportion"] for entry in result["categories"]] == pytest.approx(
        [1 / 3, 1 / 3, 1 / 3]
    )
    assert [entry["expected_count"] for entry in result["categories"]] == pytest.approx(
        [100 / 3, 100 / 3, 100 / 3]
    )


def test_gof_equal_proportions_statistic_matches_hand_computation() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_gof_test(_gof_df(), "cat")
    # e = 100/3; chi2 = ((30-e)^2 + (30-e)^2 + (40-e)^2)/e = 2.0
    assert result["statistic"] == pytest.approx(2.0)
    assert result["degrees_of_freedom"] == 2
    assert result["p_value"] == pytest.approx(float(np.exp(-1.0)), rel=1e-6)
    assert result["reject_null"] is False
    assert result["method"] == "chi_square_goodness_of_fit"
    assert result["scipy_available"] is True


# ── CHI_GOF: custom proportions ───────────────────────────────────────────────


def test_gof_custom_proportions_perfect_fit() -> None:
    pytest.importorskip("scipy")
    df = _gof_df()
    expected = _expected_by_label(df, "cat", {"a [str]": 0.3, "b [str]": 0.3, "c [str]": 0.4})
    result = svc.run_chi_square_gof_test(df, "cat", expected_proportions=expected)
    assert result["status"] == "ok"
    assert result["expected_mode"] == "custom"
    assert result["statistic"] == pytest.approx(0.0)
    assert result["p_value"] == pytest.approx(1.0)
    assert [entry["expected_count"] for entry in result["categories"]] == pytest.approx(
        [30.0, 30.0, 40.0]
    )


def test_gof_custom_proportions_mapping_is_exact() -> None:
    pytest.importorskip("scipy")
    df = _gof_df()
    expected = _expected_by_label(df, "cat", {"a [str]": 0.5, "b [str]": 0.25, "c [str]": 0.25})
    result = svc.run_chi_square_gof_test(df, "cat", expected_proportions=expected)
    assert result["status"] == "ok"
    # Expected counts follow the exact category→proportion mapping (50/25/25).
    assert [entry["expected_count"] for entry in result["categories"]] == pytest.approx(
        [50.0, 25.0, 25.0]
    )
    # chi2 = 400/50 + 25/25 + 225/25 = 18.0
    assert result["statistic"] == pytest.approx(18.0)


def test_gof_custom_proportions_not_summing_to_one_rejected() -> None:
    df = _gof_df()
    expected = _expected_by_label(df, "cat", {"a [str]": 0.5, "b [str]": 0.5, "c [str]": 0.5})
    result = svc.run_chi_square_gof_test(df, "cat", expected_proportions=expected)
    assert result["status"] == "invalid_input"
    assert "sum to 1" in str(result["reason"])


def test_gof_custom_zero_proportion_rejected() -> None:
    df = _gof_df()
    expected = _expected_by_label(df, "cat", {"a [str]": 0.0, "b [str]": 0.5, "c [str]": 0.5})
    result = svc.run_chi_square_gof_test(df, "cat", expected_proportions=expected)
    assert result["status"] == "invalid_input"
    assert "greater than zero" in str(result["reason"])


def test_gof_custom_negative_proportion_rejected() -> None:
    df = _gof_df()
    expected = _expected_by_label(df, "cat", {"a [str]": -0.1, "b [str]": 0.6, "c [str]": 0.5})
    result = svc.run_chi_square_gof_test(df, "cat", expected_proportions=expected)
    assert result["status"] == "invalid_input"
    assert "greater than zero" in str(result["reason"])


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_gof_custom_non_finite_proportion_rejected(bad: float) -> None:
    df = _gof_df()
    expected = _expected_by_label(df, "cat", {"a [str]": bad, "b [str]": 0.5, "c [str]": 0.5})
    result = svc.run_chi_square_gof_test(df, "cat", expected_proportions=expected)
    assert result["status"] == "invalid_input"
    assert "finite" in str(result["reason"])


def test_gof_custom_missing_category_mapping_rejected() -> None:
    df = _gof_df()
    options = _gof_options(df, "cat")
    # Drop the last category from the mapping.
    expected = {options[0].identity: 0.5, options[1].identity: 0.5}
    result = svc.run_chi_square_gof_test(df, "cat", expected_proportions=expected)
    assert result["status"] == "invalid_input"
    assert "missing expected proportion" in str(result["reason"])


# ── CHI_GOF: typed category identity + collision safety ───────────────────────


def test_gof_typed_collisions_kept_distinct() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame({"cat": pd.Series([1, "1", 1, "1", 2], dtype=object)})
    result = svc.run_chi_square_gof_test(df, "cat")
    assert result["status"] == "ok"
    # int 1, str "1", int 2 are three distinct typed categories (labels sorted).
    assert result["observed_values"] == ["1 [int]", "1 [str]", "2 [int]"]
    assert result["observed_counts"] == [2, 2, 1]


def test_gof_unresolved_collision_rejected() -> None:
    class Ambiguous:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def __str__(self) -> str:
            return "same"

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Ambiguous) and self.tag == other.tag

        def __hash__(self) -> int:
            return hash(("ambiguous", self.tag))

    df = pd.DataFrame({"cat": pd.Series([Ambiguous("x"), Ambiguous("y")], dtype=object)})
    result = svc.run_chi_square_gof_test(df, "cat")
    assert result["status"] == "invalid_input"
    assert "unambiguously" in str(result["reason"])
    assert result["statistic"] is None


def test_gof_opaque_object_rejected_without_address() -> None:
    df = pd.DataFrame({"cat": pd.Series([object(), "ok", object()], dtype=object)})
    result = svc.run_chi_square_gof_test(df, "cat")
    assert result["status"] == "invalid_input"
    assert "0x" not in str(result["reason"])
    assert "object at" not in str(result["reason"]).lower()


def test_gof_different_modules_same_classname_disambiguated() -> None:
    pytest.importorskip("scipy")

    def _status_class(module_name: str) -> type:
        class Status:
            def __init__(self, text: str) -> None:
                self._text = text

            def __str__(self) -> str:
                return self._text

            def __eq__(self, other: object) -> bool:
                return isinstance(other, Status) and self._text == other._text

            def __hash__(self) -> int:
                return hash((module_name, self._text))

        Status.__module__ = module_name
        return Status

    a = _status_class("pkg_a.statuses")("Open")
    b = _status_class("pkg_b.statuses")("Open")
    df = pd.DataFrame({"cat": pd.Series([a, a, b], dtype=object)})
    result = svc.run_chi_square_gof_test(df, "cat")
    assert result["status"] == "ok"
    joined = " ".join(result["observed_values"])
    assert "pkg_a.statuses" in joined and "pkg_b.statuses" in joined
    assert "0x" not in joined


# ── CHI_GOF: scipy degradation + alpha ────────────────────────────────────────


def test_gof_invalid_alpha_structured() -> None:
    result = svc.run_chi_square_gof_test(_gof_df(), "cat", alpha=1.5)
    assert result["status"] == "invalid_input"


def test_gof_scipy_unavailable_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    result = svc.run_chi_square_gof_test(_gof_df(), "cat")
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    # Prepared evidence is still attached without a live kernel result.
    assert result["valid_rows"] == 100
    assert result["observed_counts"] == [30, 30, 40]
    assert [entry["category"] for entry in result["categories"]] == [
        "a [str]",
        "b [str]",
        "c [str]",
    ]


# ── CHI_IND: shared helpers ───────────────────────────────────────────────────


def _df_from_table(
    observed: list[list[int]],
    row_labels: list[Any],
    col_labels: list[Any],
    *,
    row_col: str = "x",
    col_col: str = "y",
) -> pd.DataFrame:
    """Expand a contingency count matrix into a tidy long DataFrame."""
    rows: list[dict[str, Any]] = []
    for i, row_label in enumerate(row_labels):
        for j, col_label in enumerate(col_labels):
            rows.extend([{row_col: row_label, col_col: col_label}] * observed[i][j])
    return pd.DataFrame(rows)


def _expected_matrix(result: dict) -> np.ndarray:
    """Reconstruct the R×C expected matrix from a contingency result's long-form cells."""
    r = int(result["row_category_count"])
    c = int(result["col_category_count"])
    row_labels = list(result["row_labels"])
    col_labels = list(result["col_labels"])
    matrix = np.zeros((r, c))
    for cell in result["cells"]:
        matrix[row_labels.index(cell["row_category"])][col_labels.index(cell["col_category"])] = (
            cell["expected"]
        )
    return matrix


# ── CHI_IND: validation ───────────────────────────────────────────────────────


def test_ind_missing_first_column_invalid() -> None:
    df = _df_from_table([[5, 5], [5, 5]], ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "nope", "y")
    assert result["status"] == "invalid_input"
    assert result["test_key"] == "CHI_IND"
    assert "not found" in str(result["reason"])


def test_ind_identical_columns_rejected() -> None:
    df = _df_from_table([[5, 5], [5, 5]], ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "x")
    assert result["status"] == "invalid_input"
    assert "different" in str(result["reason"])


def test_ind_single_category_axis_rejected() -> None:
    df = pd.DataFrame({"x": ["A", "A", "A"], "y": ["P", "Q", "P"]})
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "invalid_input"
    assert "at least two distinct" in str(result["reason"])


def test_ind_no_valid_rows_insufficient() -> None:
    df = pd.DataFrame({"x": [None, np.nan], "y": [np.nan, None]})
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "insufficient_data"
    assert result["valid_rows"] == 0


def test_ind_has_no_one_sided_control() -> None:
    params = inspect.signature(svc.run_chi_square_independence_test).parameters
    assert "alternative" not in params


# ── CHI_IND: partition + table ────────────────────────────────────────────────


def test_ind_missing_and_non_finite_rows_excluded() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "x": ["A", "B", "A", "B", None, 1.0],
            "y": ["P", "Q", "Q", "P", "P", np.inf],
        }
    )
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["total_rows"] == 6
    assert result["valid_rows"] == 4  # the None row and the +inf row are excluded
    assert result["excluded_rows"] == 2
    assert result["valid_rows"] + result["excluded_rows"] == result["total_rows"]


def test_ind_observed_and_expected_match_scipy() -> None:
    scipy_stats = pytest.importorskip("scipy.stats")
    observed = [[30, 10], [10, 30]]
    df = _df_from_table(observed, ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "ok"
    assert result["test_key"] == "CHI_IND"
    assert result["method"] == "chi_square_independence"
    assert result["degrees_of_freedom"] == 1
    # observed counts reconstructed from the long-form cells match the source table.
    cells = {(c["row_category"], c["col_category"]): c["observed"] for c in result["cells"]}
    assert cells[("A [str]", "P [str]")] == 30
    assert cells[("B [str]", "Q [str]")] == 30
    # derived expected matches the real scipy contingency expected frequencies.
    chi2, p, dof, expected = scipy_stats.chi2_contingency(np.asarray(observed))
    assert result["statistic"] == pytest.approx(float(chi2))
    assert result["p_value"] == pytest.approx(float(p))
    assert np.allclose(_expected_matrix(result), expected)


def test_ind_deterministic_axis_order() -> None:
    pytest.importorskip("scipy")
    df = _df_from_table([[1, 2, 3], [4, 5, 6]], ["B", "A"], ["Z", "Y", "X"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["row_labels"] == ["A [str]", "B [str]"]
    assert result["col_labels"] == ["X [str]", "Y [str]", "Z [str]"]


# ── CHI_IND: typed identity + collision safety on both axes ───────────────────


def test_ind_typed_identity_both_axes() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "x": pd.Series([1, "1", 1, "1"], dtype=object),
            "y": pd.Series([1, 1, "1", "1"], dtype=object),
        }
    )
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "ok"
    assert result["row_labels"] == ["1 [int]", "1 [str]"]
    assert result["col_labels"] == ["1 [int]", "1 [str]"]


def test_ind_module_qualified_labels_both_axes() -> None:
    pytest.importorskip("scipy")

    def _status_class(module_name: str) -> type:
        class Status:
            def __init__(self, text: str) -> None:
                self._text = text

            def __str__(self) -> str:
                return self._text

            def __eq__(self, other: object) -> bool:
                return isinstance(other, Status) and self._text == other._text

            def __hash__(self) -> int:
                return hash((module_name, self._text))

        Status.__module__ = module_name
        return Status

    a = _status_class("pkg_a.rows")("G")
    b = _status_class("pkg_b.rows")("G")
    df = pd.DataFrame(
        {
            "x": pd.Series([a, a, b, b], dtype=object),
            "y": ["P", "Q", "P", "Q"],
        }
    )
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "ok"
    joined = " ".join(result["row_labels"])
    assert "pkg_a.rows" in joined and "pkg_b.rows" in joined


def test_ind_unresolved_collision_rejected() -> None:
    class Ambiguous:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def __str__(self) -> str:
            return "same"

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Ambiguous) and self.tag == other.tag

        def __hash__(self) -> int:
            return hash(("ambiguous", self.tag))

    df = pd.DataFrame(
        {
            "x": pd.Series([Ambiguous("x"), Ambiguous("y")], dtype=object),
            "y": ["P", "Q"],
        }
    )
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "invalid_input"
    assert "unambiguously" in str(result["reason"])


def test_ind_opaque_object_rejected_without_address() -> None:
    df = pd.DataFrame({"x": pd.Series([object(), "ok"], dtype=object), "y": ["P", "Q"]})
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "invalid_input"
    assert "0x" not in str(result["reason"])
    assert "object at" not in str(result["reason"]).lower()


# ── CHI_IND: expected-frequency diagnostics (informational) ───────────────────


def test_ind_expected_below_one_warns() -> None:
    pytest.importorskip("scipy")
    # Row/col total of 1 against a large grand total drives an expected cell to 0.01.
    observed = [[1, 0], [0, 99]]
    df = _df_from_table(observed, ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "ok"
    joined = " ".join(result["warnings"]).lower()
    assert "below 1" in joined


def test_ind_more_than_20pct_below_5_warns_without_below_one() -> None:
    pytest.importorskip("scipy")
    # Expected = [[2.5, 7.5], [7.5, 22.5]]: min 2.5 (>=1) but 25% of cells below 5.
    observed = [[5, 5], [5, 25]]
    df = _df_from_table(observed, ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "ok"
    joined = " ".join(result["warnings"]).lower()
    assert "below 5" in joined
    assert "below 1" not in joined


def test_ind_large_balanced_table_has_no_diagnostics() -> None:
    pytest.importorskip("scipy")
    observed = [[25, 25], [25, 25]]
    df = _df_from_table(observed, ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "ok"
    assert result["warnings"] == []


def test_ind_diagnostic_does_not_switch_test() -> None:
    pytest.importorskip("scipy")
    observed = [[1, 0], [0, 99]]
    df = _df_from_table(observed, ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    # Even with a small-cell warning, the test key and method are unchanged.
    assert result["test_key"] == "CHI_IND"
    assert result["method"] == "chi_square_independence"


# ── CHI_IND: scipy degradation + alpha ────────────────────────────────────────


def test_ind_invalid_alpha_structured() -> None:
    df = _df_from_table([[5, 5], [5, 5]], ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y", alpha=1.5)
    assert result["status"] == "invalid_input"


def test_ind_scipy_unavailable_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    df = _df_from_table([[30, 10], [10, 30]], ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    # Prepared evidence (counts + cells) is still attached without a live kernel result.
    assert result["valid_rows"] == 80
    assert len(result["cells"]) == 4


# ── CHI_HOMOG ─────────────────────────────────────────────────────────────────


def _homog_df(observed: list[list[int]] | None = None) -> pd.DataFrame:
    observed = observed or [[30, 10], [10, 30]]
    return _df_from_table(observed, ["G1", "G2"], ["yes", "no"], row_col="grp", col_col="out")


def test_homog_missing_group_column_invalid() -> None:
    result = svc.run_chi_square_homogeneity_test(_homog_df(), "nope", "out")
    assert result["status"] == "invalid_input"
    assert result["test_key"] == "CHI_HOMOG"
    assert "not found" in str(result["reason"])


def test_homog_identical_columns_rejected() -> None:
    result = svc.run_chi_square_homogeneity_test(_homog_df(), "grp", "grp")
    assert result["status"] == "invalid_input"
    assert "different" in str(result["reason"])


def test_homog_fewer_than_two_groups_rejected() -> None:
    df = pd.DataFrame({"grp": ["G1", "G1", "G1"], "out": ["yes", "no", "yes"]})
    result = svc.run_chi_square_homogeneity_test(df, "grp", "out")
    assert result["status"] == "invalid_input"
    assert "group column" in str(result["reason"])
    assert "at least two distinct" in str(result["reason"])


def test_homog_fewer_than_two_outcomes_rejected() -> None:
    df = pd.DataFrame({"grp": ["G1", "G2", "G1"], "out": ["yes", "yes", "yes"]})
    result = svc.run_chi_square_homogeneity_test(df, "grp", "out")
    assert result["status"] == "invalid_input"
    assert "outcome column" in str(result["reason"])
    assert "at least two distinct" in str(result["reason"])


def test_homog_no_valid_rows_insufficient() -> None:
    df = pd.DataFrame({"grp": [None, np.nan], "out": [np.nan, None]})
    result = svc.run_chi_square_homogeneity_test(df, "grp", "out")
    assert result["status"] == "insufficient_data"
    assert result["valid_rows"] == 0


def test_homog_missing_and_non_finite_excluded() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "grp": ["G1", "G2", "G1", "G2", None, 1.0],
            "out": ["yes", "no", "no", "yes", "yes", np.inf],
        }
    )
    result = svc.run_chi_square_homogeneity_test(df, "grp", "out")
    assert result["total_rows"] == 6
    assert result["valid_rows"] == 4
    assert result["excluded_rows"] == 2


def test_homog_has_no_one_sided_control() -> None:
    params = inspect.signature(svc.run_chi_square_homogeneity_test).parameters
    assert "alternative" not in params


def test_homog_orientation_groups_on_rows_outcomes_on_columns() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_homogeneity_test(_homog_df(), "grp", "out")
    assert result["status"] == "ok"
    # Populations/groups on the row axis; outcome categories on the column axis.
    assert result["row_labels"] == ["G1 [str]", "G2 [str]"]
    assert result["col_labels"] == ["no [str]", "yes [str]"]
    assert result["group_column"] == "grp"
    assert result["outcome_column"] == "out"


def test_homog_uses_own_key_not_independence() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_homogeneity_test(_homog_df(), "grp", "out")
    assert result["test_key"] == "CHI_HOMOG"
    assert result["test_key"] != "CHI_IND"
    assert result["method"] == "chi_square_homogeneity"


def test_homog_reuses_shared_contingency_primitive() -> None:
    pytest.importorskip("scipy")
    df = _homog_df()
    homogeneity = svc.run_chi_square_homogeneity_test(df, "grp", "out")
    # The independence runner over the same two columns builds the same observed table
    # through the shared primitive, so the statistic/p/dof agree while the keys differ.
    independence = svc.run_chi_square_independence_test(df, "grp", "out")
    assert homogeneity["statistic"] == pytest.approx(independence["statistic"])
    assert homogeneity["p_value"] == pytest.approx(independence["p_value"])
    assert homogeneity["degrees_of_freedom"] == independence["degrees_of_freedom"]
    assert homogeneity["test_key"] != independence["test_key"]


def test_homog_observed_and_expected_match_scipy() -> None:
    scipy_stats = pytest.importorskip("scipy.stats")
    observed = [[30, 10], [10, 30]]
    df = _df_from_table(observed, ["G1", "G2"], ["yes", "no"], row_col="grp", col_col="out")
    result = svc.run_chi_square_homogeneity_test(df, "grp", "out")
    chi2, p, dof, expected = scipy_stats.chi2_contingency(np.asarray(observed))
    assert result["statistic"] == pytest.approx(float(chi2))
    assert result["p_value"] == pytest.approx(float(p))
    assert result["degrees_of_freedom"] == int(dof)
    assert np.allclose(_expected_matrix(result), expected)


def test_homog_typed_identity_both_dimensions() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "grp": pd.Series([1, "1", 1, "1"], dtype=object),
            "out": pd.Series([1, 1, "1", "1"], dtype=object),
        }
    )
    result = svc.run_chi_square_homogeneity_test(df, "grp", "out")
    assert result["status"] == "ok"
    assert result["row_labels"] == ["1 [int]", "1 [str]"]
    assert result["col_labels"] == ["1 [int]", "1 [str]"]


def test_homog_unresolved_collision_rejected() -> None:
    class Ambiguous:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def __str__(self) -> str:
            return "same"

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Ambiguous) and self.tag == other.tag

        def __hash__(self) -> int:
            return hash(("ambiguous", self.tag))

    df = pd.DataFrame(
        {"grp": pd.Series([Ambiguous("x"), Ambiguous("y")], dtype=object), "out": ["yes", "no"]}
    )
    result = svc.run_chi_square_homogeneity_test(df, "grp", "out")
    assert result["status"] == "invalid_input"
    assert "unambiguously" in str(result["reason"])


def test_homog_expected_frequency_diagnostics_reused() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_homogeneity_test(_homog_df([[1, 0], [0, 99]]), "grp", "out")
    assert result["status"] == "ok"
    assert "below 1" in " ".join(result["warnings"]).lower()
    # The diagnostic never switches the test.
    assert result["test_key"] == "CHI_HOMOG"


def test_homog_invalid_alpha_structured() -> None:
    result = svc.run_chi_square_homogeneity_test(_homog_df(), "grp", "out", alpha=1.5)
    assert result["status"] == "invalid_input"


def test_homog_scipy_unavailable_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    result = svc.run_chi_square_homogeneity_test(_homog_df(), "grp", "out")
    assert result["status"] == "unavailable"
    assert result["scipy_available"] is False
    assert result["valid_rows"] == 80
    assert len(result["cells"]) == 4


# ── diagnostics ownership: the service presents, the kernel decides ───────────


def test_service_owns_no_expected_frequency_rule() -> None:
    """No second authoritative copy of the expected-count thresholds lives in the UI."""
    source = inspect.getsource(svc)
    assert "_expected_frequency_warnings" not in source
    assert "_EXPECTED_SMALL_CELL_FRACTION" not in source


def test_gof_sparse_expected_counts_surface_the_backend_diagnostic() -> None:
    pytest.importorskip("scipy")
    # Four categories over four rows: every expected count is 1.0 under equal
    # proportions, and one observed-driven custom split pushes cells below 1.
    df = pd.DataFrame({"cat": ["a", "b", "c", "d"]})
    result = svc.run_chi_square_gof_test(df, "cat")
    assert result["status"] == "ok"
    joined = " ".join(result["warnings"]).lower()
    assert "below 5" in joined
    assert result["assumptions"]["expected_counts"]["over_20pct_below_5"] is True


def test_gof_healthy_table_has_no_sparse_warning() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_gof_test(_gof_df(), "cat")
    assert result["status"] == "ok"
    assert result["warnings"] == []
    assert result["assumptions"]["expected_counts"]["sparse"] is False


def test_gof_warnings_are_exactly_the_backend_warnings() -> None:
    pytest.importorskip("scipy")
    from data_quality_toolkit.domain.statistics import inference

    df = pd.DataFrame({"cat": ["a", "b", "c", "d"]})
    result = svc.run_chi_square_gof_test(df, "cat")
    backend = inference.calculate_p_value(
        "CHI_GOF",
        observed=result["observed_counts"],
        expected=[cell["expected_count"] for cell in result["categories"]],
    )
    assert result["warnings"] == backend["warnings"]


def test_contingency_warnings_are_exactly_the_backend_warnings() -> None:
    pytest.importorskip("scipy")
    from data_quality_toolkit.domain.statistics import inference

    observed = [[1, 0], [0, 99]]
    df = _df_from_table(observed, ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    backend = inference.calculate_p_value("CHI_IND", table=observed)
    assert result["warnings"] == backend["warnings"]
    assert result["assumptions"] == backend["assumptions"]


def test_contingency_result_carries_structured_expected_count_diagnostics() -> None:
    pytest.importorskip("scipy")
    df = _df_from_table([[5, 5], [5, 25]], ["A", "B"], ["P", "Q"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    diagnostics = result["assumptions"]["expected_counts"]
    assert diagnostics["cells_below_5"] == 1
    assert diagnostics["fraction_below_5"] == pytest.approx(0.25)


def test_homog_diagnostics_come_from_the_same_backend_contract() -> None:
    pytest.importorskip("scipy")
    from data_quality_toolkit.domain.statistics import inference

    observed = [[1, 0], [0, 99]]
    result = svc.run_chi_square_homogeneity_test(_homog_df(observed), "grp", "out")
    backend = inference.calculate_p_value("CHI_HOMOG", table=observed)
    assert result["warnings"] == backend["warnings"]
    assert result["test_key"] == "CHI_HOMOG"


def test_contingency_2x2_continuity_correction_is_disclosed_to_the_ui() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_independence_test(_homog_df(), "grp", "out")
    assert result["assumptions"]["continuity_correction"] is True
    assert "continuity correction" in " ".join(result["messages"]).lower()


def test_contingency_wider_table_is_not_told_a_correction_was_applied() -> None:
    pytest.importorskip("scipy")
    df = _df_from_table([[10, 20, 5], [30, 40, 5]], ["A", "B"], ["P", "Q", "R"])
    result = svc.run_chi_square_independence_test(df, "x", "y")
    assert result["assumptions"]["continuity_correction"] is False
    assert result["messages"] == []


# ── F2: service-side categorical ceiling (independent of any page selector) ──

_PATHOLOGICAL_LEVELS = 74_111


def _levels_frame(levels: int, *, repeats: int = 4, column: str = "cat") -> pd.DataFrame:
    return pd.DataFrame(
        {column: [f"level_{index:05d}" for index in range(levels) for _ in range(repeats)]}
    )


def _wide_pair_frame(row_levels: int, col_levels: int) -> pd.DataFrame:
    rows = max(row_levels, col_levels) * 2
    return pd.DataFrame(
        {
            "x": [f"r_{index % row_levels:06d}" for index in range(rows)],
            "y": [f"c_{index % col_levels:06d}" for index in range(rows)],
        }
    )


def _no_allocation(monkeypatch: pytest.MonkeyPatch, *rejected: str) -> None:
    """Fail loudly if a rejected column reaches category or matrix construction.

    A safe companion axis may legitimately be labelled before the unsafe axis is
    reached, so only the named columns are forbidden; the expected-count matrix is
    forbidden outright, because no rejected input may ever allocate one.
    """
    real = svc._typed_categories

    def guarded(values: Any, column: str) -> Any:
        assert (
            column not in rejected
        ), f"typed category construction was reached for rejected column {column!r}"
        return real(values, column)

    def forbidden_outer(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("an expected-count matrix was allocated for a rejected input")

    monkeypatch.setattr(svc, "_typed_categories", guarded)
    monkeypatch.setattr(svc.np, "outer", forbidden_outer)


def test_gof_accepts_exactly_fifty_categories() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_gof_test(_levels_frame(50), "cat")
    assert result["status"] == "ok"
    assert result["category_count"] == 50
    assert result["degrees_of_freedom"] == 49


def test_gof_rejects_fifty_one_categories() -> None:
    result = svc.run_chi_square_gof_test(_levels_frame(51), "cat")
    assert result["status"] == "invalid_input"
    assert "51 distinct non-missing values" in str(result["reason"])
    assert "limited to 50 distinct categories" in str(result["reason"])


def test_gof_ceiling_runs_before_any_category_payload_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_allocation(monkeypatch, "cat")
    result = svc.run_chi_square_gof_test(_levels_frame(_PATHOLOGICAL_LEVELS, repeats=1), "cat")
    assert result["status"] == "invalid_input"
    assert "categories" not in result
    assert "observed_values" not in result
    assert "observed_counts" not in result


def test_gof_rejection_reason_enumerates_no_category(monkeypatch: pytest.MonkeyPatch) -> None:
    result = svc.run_chi_square_gof_test(_levels_frame(_PATHOLOGICAL_LEVELS, repeats=1), "cat")
    reason = str(result["reason"])
    assert "74,111" in reason
    assert "level_" not in reason
    assert len(reason) < 200


def test_independence_accepts_the_fifty_level_safety_boundary() -> None:
    pytest.importorskip("scipy")
    result = svc.run_chi_square_independence_test(_wide_pair_frame(50, 50), "x", "y")
    assert result["status"] in {"ok", "unavailable"}
    if result["status"] == "ok":
        assert result["row_category_count"] == 50
        assert result["col_category_count"] == 50


def test_independence_rejects_a_fifty_one_level_row_axis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_allocation(monkeypatch, "x")
    result = svc.run_chi_square_independence_test(_wide_pair_frame(51, 3), "x", "y")
    assert result["status"] == "invalid_input"
    assert "first column 'x'" in str(result["reason"])
    assert "cells" not in result


def test_independence_rejects_a_fifty_one_level_column_axis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_allocation(monkeypatch, "y")
    result = svc.run_chi_square_independence_test(_wide_pair_frame(3, 51), "x", "y")
    assert result["status"] == "invalid_input"
    assert "second column 'y'" in str(result["reason"])
    assert "cells" not in result


def test_homogeneity_rejects_a_pathological_axis_without_allocating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_allocation(monkeypatch, "grp")
    frame = pd.DataFrame(
        {
            "grp": [f"id_{index:06d}" for index in range(_PATHOLOGICAL_LEVELS)],
            "out": ["yes" if index % 2 else "no" for index in range(_PATHOLOGICAL_LEVELS)],
        }
    )
    result = svc.run_chi_square_homogeneity_test(frame, "grp", "out")
    assert result["status"] == "invalid_input"
    reason = str(result["reason"])
    assert "74,111" in reason
    assert "id_000000" not in reason
    assert "cells" not in result


def test_contingency_ceiling_does_not_change_a_small_table() -> None:
    pytest.importorskip("scipy")
    frame = _assoc_frame_for_ceiling()
    result = svc.run_chi_square_independence_test(frame, "x", "y")
    assert result["status"] == "ok"
    assert result["row_category_count"] == 2
    assert result["col_category_count"] == 2
    assert result["degrees_of_freedom"] == 1


def _assoc_frame_for_ceiling() -> pd.DataFrame:
    observed = [[30, 10], [10, 30]]
    rows: list[dict[str, Any]] = []
    for i, row_label in enumerate(["A", "B"]):
        for j, col_label in enumerate(["P", "Q"]):
            rows.extend([{"x": row_label, "y": col_label}] * observed[i][j])
    return pd.DataFrame(rows)
