"""Pure-builder tests for the P2 EDA visual-discovery expansion.

Covers the Q-Q diagnostic, Pareto concentration view, structural missingness
(pattern matrix + association), ranked relationship pairs, and the bounded
categorical association matrix. Every builder here must be deterministic,
framework-free, non-mutating, and safe on degenerate input. Synthetic frames
only — no fixtures, datasets, or generated artifacts.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.eda import (
    CATEGORICAL_ASSOC_MAX_COLUMNS,
    CATEGORICAL_ASSOC_MAX_LEVELS,
    CATEGORICAL_ASSOC_MAX_ROWS,
    GENERAL_VISUAL_MAX_ROWS,
    GUIDE_MAX_RECOMMENDATIONS,
    MAX_PLOT_ROWS,
    MISSINGNESS_ASSOC_MAX_COLUMNS,
    MISSINGNESS_ASSOC_MAX_ROWS,
    MISSINGNESS_PATTERN_MAX_COLUMNS,
    MISSINGNESS_PATTERN_MAX_ROWS,
    NUMERIC_CORRELATION_MAX_COLUMNS,
    PARETO_MAX_CATEGORIES,
    PARETO_MIN_CATEGORY_COUNT,
    QQ_MAX_POINTS,
    QQ_MIN_OBSERVATIONS,
    TOP_RELATIONSHIP_PAIRS,
    _capped_levels,
    _categorical_association_data,
    _correlation_heatmap_data,
    _cramers_v,
    _deterministic_row_positions,
    _missingness_association_data,
    _missingness_pattern_data,
    _numeric_correlation_columns,
    _pareto_category_data,
    _qq_normal_data,
    _ranked_matrix_pairs,
)

# ── declared performance bounds ──────────────────────────────────────────────


def test_declared_bounds_do_not_exceed_the_admitted_ceilings() -> None:
    assert GENERAL_VISUAL_MAX_ROWS <= 5_000
    assert QQ_MAX_POINTS <= 1_000
    assert MISSINGNESS_PATTERN_MAX_ROWS <= 200
    assert MISSINGNESS_PATTERN_MAX_COLUMNS <= 40
    assert MISSINGNESS_ASSOC_MAX_ROWS <= 5_000
    assert MISSINGNESS_ASSOC_MAX_COLUMNS <= 20
    assert NUMERIC_CORRELATION_MAX_COLUMNS <= 20
    assert CATEGORICAL_ASSOC_MAX_ROWS <= 5_000
    assert CATEGORICAL_ASSOC_MAX_COLUMNS <= 8
    assert CATEGORICAL_ASSOC_MAX_LEVELS <= 20
    assert PARETO_MAX_CATEGORIES <= 20
    assert GUIDE_MAX_RECOMMENDATIONS <= 8
    assert TOP_RELATIONSHIP_PAIRS <= 15
    # The general visual row bound is the existing plot cap, not a second value.
    assert GENERAL_VISUAL_MAX_ROWS == MAX_PLOT_ROWS


def test_deterministic_row_positions_are_bounded_ordered_and_repeatable() -> None:
    positions = _deterministic_row_positions(10_000, 50)
    assert len(positions) <= 50
    assert positions[0] == 0
    assert positions[-1] == 9_999
    assert list(positions) == sorted(positions)
    assert list(positions) == list(_deterministic_row_positions(10_000, 50))
    # Small frames are returned whole.
    assert list(_deterministic_row_positions(3, 50)) == [0, 1, 2]


# ── Q-Q visual diagnostic ────────────────────────────────────────────────────


def _qq_series(n: int = 40) -> pd.Series:
    return pd.Series([float(i) for i in range(n)])


def test_qq_valid_numeric_returns_ordered_theoretical_and_observed() -> None:
    result = _qq_normal_data(_qq_series())

    assert result["status"] == "ok"
    assert list(result["data"].columns) == ["theoretical_quantile", "observed_value"]
    theoretical = result["data"]["theoretical_quantile"].tolist()
    observed = result["data"]["observed_value"].tolist()
    assert theoretical == sorted(theoretical)
    assert observed == sorted(observed)
    assert result["observations"] == 40


def test_qq_reference_line_uses_two_endpoints_from_location_and_scale() -> None:
    result = _qq_normal_data(_qq_series())

    reference = result["reference"]
    assert len(reference) == 2
    assert result["scale"] > 0
    expected_low = result["location"] + result["scale"] * reference["theoretical_quantile"].iloc[0]
    assert reference["observed_value"].iloc[0] == pytest.approx(expected_low, abs=1e-5)


def test_qq_empty_all_null_and_short_inputs_are_insufficient() -> None:
    assert _qq_normal_data(pd.Series([], dtype="float64"))["status"] == "insufficient_data"
    all_null = pd.Series([None] * 20, dtype="float64")
    assert _qq_normal_data(all_null)["status"] == "insufficient_data"
    short = pd.Series([float(i) for i in range(QQ_MIN_OBSERVATIONS - 1)])
    result = _qq_normal_data(short)
    assert result["status"] == "insufficient_data"
    assert result["data"].empty


def test_qq_constant_column_reports_insufficient_variation() -> None:
    result = _qq_normal_data(pd.Series([7.0] * 30))

    assert result["status"] == "insufficient_variation"
    assert result["data"].empty


def test_qq_non_numeric_column_is_refused_without_raising() -> None:
    result = _qq_normal_data(pd.Series(["a", "b", "c", "d", "e", "f", "g", "h", "i"]))

    assert result["status"] == "invalid_type"
    assert result["data"].empty


def test_qq_numeric_like_strings_are_coerced_safely() -> None:
    result = _qq_normal_data(pd.Series([str(i) for i in range(20)]))

    assert result["status"] == "ok"
    assert result["observations"] == 20


def test_qq_ignores_nan_and_infinite_values() -> None:
    values = [float(i) for i in range(20)] + [float("nan"), float("inf"), float("-inf")]
    result = _qq_normal_data(pd.Series(values))

    assert result["status"] == "ok"
    assert result["observations"] == 20


def test_qq_point_cap_is_enforced_and_deterministic() -> None:
    series = pd.Series([float(i) for i in range(QQ_MAX_POINTS * 5)])

    first = _qq_normal_data(series)
    second = _qq_normal_data(series)

    assert first["status"] == "ok"
    assert first["sampled"] is True
    assert first["points"] <= QQ_MAX_POINTS
    assert first["observations"] == QQ_MAX_POINTS * 5
    pd.testing.assert_frame_equal(first["data"], second["data"])


def test_qq_custom_point_cap_preserves_the_extremes() -> None:
    series = pd.Series([float(i) for i in range(500)])

    result = _qq_normal_data(series, max_points=25)

    assert result["points"] <= 25
    assert result["data"]["observed_value"].iloc[0] == pytest.approx(0.0)
    assert result["data"]["observed_value"].iloc[-1] == pytest.approx(499.0)


def test_qq_does_not_mutate_the_input_series() -> None:
    series = pd.Series([3.0, 1.0, float("nan"), 2.0, float("inf")] * 5)
    before = series.copy(deep=True)

    _qq_normal_data(series)

    pd.testing.assert_series_equal(series, before)


def test_qq_reports_no_p_value_or_test_verdict() -> None:
    result = _qq_normal_data(_qq_series())

    keys = {str(key).lower() for key in result}
    assert not any("p_value" in key or "pvalue" in key or "significan" in key for key in keys)


# ── Pareto concentration view ────────────────────────────────────────────────


def _pareto_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"c": ["a"] * 20 + ["b"] * 12 + ["c"] * 8 + ["d"] * 6 + ["rare"] * 2 + ["rarer"] * 1}
    )


def test_pareto_orders_by_count_then_stable_string_tie_break() -> None:
    df = pd.DataFrame({"c": ["b"] * 5 + ["a"] * 5 + ["c"] * 5})

    result = _pareto_category_data(df, "c", min_category_count=0)

    assert result["status"] == "ok"
    assert result["data"]["category"].tolist() == ["a", "b", "c"]


def test_pareto_cumulative_percentage_is_monotonic_and_reaches_one_hundred() -> None:
    result = _pareto_category_data(_pareto_frame(), "c")

    cumulative = result["data"]["cumulative_pct"].tolist()
    assert cumulative == sorted(cumulative)
    assert cumulative[-1] == pytest.approx(100.0)
    assert result["data"]["count"].sum() == result["total_count"]


def test_pareto_suppresses_rare_categories_into_the_other_bucket() -> None:
    result = _pareto_category_data(_pareto_frame(), "c")

    categories = result["data"]["category"].tolist()
    assert "rare" not in categories
    assert "rarer" not in categories
    assert "(other)" in categories
    assert result["suppressed_categories"] == 2
    assert result["other_count"] == 3
    assert result["min_category_count"] == PARETO_MIN_CATEGORY_COUNT


def test_pareto_groups_the_tail_beyond_the_visible_cap() -> None:
    df = pd.DataFrame({"c": [f"cat-{i // 6}" for i in range(60)]})

    result = _pareto_category_data(df, "c", max_categories=3)

    assert result["displayed_categories"] == 4  # 3 kept + (other)
    assert result["grouped_categories"] == 7
    assert result["truncated"] is True
    assert result["data"]["category"].iloc[-1] == "(other)"


def test_pareto_preserves_an_explicit_missing_bucket() -> None:
    df = pd.DataFrame({"c": ["a"] * 10 + [None] * 2})

    result = _pareto_category_data(df, "c", include_missing=True)

    assert "(missing)" in result["data"]["category"].tolist()
    assert result["total_count"] == 12


def test_pareto_refuses_identifier_like_columns() -> None:
    df = pd.DataFrame({"id": [f"row-{i}" for i in range(100)]})

    result = _pareto_category_data(df, "id")

    assert result["status"] == "near_unique"
    assert result["data"].empty


def test_pareto_rejects_numeric_and_missing_columns() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "c"]})

    assert _pareto_category_data(df, "n")["status"] == "invalid_type"
    assert _pareto_category_data(df, "nope")["status"] == "invalid_column"


def test_pareto_all_null_column_returns_safe_empty_state() -> None:
    df = pd.DataFrame({"c": pd.Series([None, None, None], dtype="object")})

    result = _pareto_category_data(df, "c")

    assert result["status"] == "no_data"
    assert result["data"].empty


def test_pareto_is_deterministic_and_does_not_mutate_input() -> None:
    df = _pareto_frame()
    before = df.copy(deep=True)

    first = _pareto_category_data(df, "c")
    second = _pareto_category_data(df, "c")

    pd.testing.assert_frame_equal(first["data"], second["data"])
    pd.testing.assert_frame_equal(df, before)


# ── structural missingness: anonymous pattern matrix ─────────────────────────


def _missing_frame(rows: int = 12) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "complete": list(range(rows)),
            "half": [None if i % 2 else float(i) for i in range(rows)],
            "sparse": [float(i) if i < 2 else None for i in range(rows)],
        },
        index=[f"source-index-{i}" for i in range(rows)],
    )


def test_missingness_pattern_returns_long_form_present_missing_state() -> None:
    result = _missingness_pattern_data(_missing_frame())

    assert result["status"] == "ok"
    assert list(result["data"].columns) == ["row_position", "column", "missing"]
    assert set(result["data"]["missing"].unique()) <= {0, 1}
    assert set(result["data"]["column"].unique()) == {"half", "sparse"}


def test_missingness_pattern_uses_anonymous_sequential_row_positions() -> None:
    df = _missing_frame()

    result = _missingness_pattern_data(df)

    positions = sorted(result["data"]["row_position"].unique().tolist())
    assert positions == list(range(len(df)))
    rendered = " ".join(str(value) for value in result["data"].to_numpy().ravel())
    assert "source-index" not in rendered


def test_missingness_pattern_never_exposes_raw_cell_values() -> None:
    df = pd.DataFrame({"secret": ["token-abc", None, "token-xyz", None]})

    result = _missingness_pattern_data(df)

    rendered = " ".join(str(value) for value in result["data"].to_numpy().ravel())
    assert "token-abc" not in rendered
    assert "token-xyz" not in rendered


def test_missingness_pattern_caps_rows_and_columns_and_discloses_truncation() -> None:
    df = pd.DataFrame(
        {f"c{i}": [None if row % (i + 2) else 1.0 for row in range(400)] for i in range(6)}
    )

    result = _missingness_pattern_data(df, max_rows=20, max_columns=3)

    assert result["plot_rows"] == 20
    assert result["row_sampled"] is True
    assert result["columns_displayed"] == 3
    assert result["column_truncated"] is True
    assert int(result["data"]["row_position"].max()) == 19
    assert len(result["data"]) == 20 * 3


def test_missingness_pattern_respects_the_declared_default_caps() -> None:
    df = pd.DataFrame({f"c{i}": [None] * 500 for i in range(MISSINGNESS_PATTERN_MAX_COLUMNS + 5)})

    result = _missingness_pattern_data(df)

    assert result["plot_rows"] <= MISSINGNESS_PATTERN_MAX_ROWS
    assert result["columns_displayed"] <= MISSINGNESS_PATTERN_MAX_COLUMNS


def test_missingness_pattern_safe_state_when_nothing_is_missing() -> None:
    result = _missingness_pattern_data(pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}))

    assert result["status"] == "no_missing_values"
    assert result["data"].empty


def test_missingness_pattern_is_deterministic_and_non_mutating() -> None:
    df = _missing_frame(300)
    before = df.copy(deep=True)

    first = _missingness_pattern_data(df, max_rows=25)
    second = _missingness_pattern_data(df, max_rows=25)

    pd.testing.assert_frame_equal(first["data"], second["data"])
    pd.testing.assert_frame_equal(df, before)


# ── structural missingness: association ──────────────────────────────────────


def _co_missing_frame(rows: int = 40) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "a": [None if i % 2 else 1.0 for i in range(rows)],
            "b": [None if i % 2 else 2.0 for i in range(rows)],
            "c": [None if i % 3 else 3.0 for i in range(rows)],
        }
    )


def test_missingness_association_is_symmetric_and_bounded() -> None:
    result = _missingness_association_data(_co_missing_frame())

    assert result["status"] == "ok"
    matrix = result["matrix"]
    pd.testing.assert_frame_equal(matrix, matrix.T)
    assert matrix.to_numpy().min() >= -1.0
    assert matrix.to_numpy().max() <= 1.0
    assert all(matrix.iloc[i, i] == pytest.approx(1.0) for i in range(matrix.shape[0]))


def test_missingness_association_detects_columns_missing_together() -> None:
    result = _missingness_association_data(_co_missing_frame())

    assert result["matrix"].loc["a", "b"] == pytest.approx(1.0)
    top = result["pairs"].iloc[0]
    assert {top["column_x"], top["column_y"]} == {"a", "b"}


def test_missingness_association_preserves_sign() -> None:
    df = pd.DataFrame(
        {
            "a": [None if i % 2 else 1.0 for i in range(40)],
            "b": [1.0 if i % 2 else None for i in range(40)],
        }
    )

    result = _missingness_association_data(df)

    assert result["matrix"].loc["a", "b"] == pytest.approx(-1.0)


def test_missingness_association_drops_columns_without_missingness_variation() -> None:
    df = pd.DataFrame(
        {
            "always_missing": [None] * 20,
            "varies": [None if i % 2 else 1.0 for i in range(20)],
            "also_varies": [None if i % 3 else 1.0 for i in range(20)],
        }
    )

    result = _missingness_association_data(df)

    assert result["status"] == "ok"
    assert "always_missing" not in result["matrix"].columns


def test_missingness_association_insufficient_columns_is_safe() -> None:
    result = _missingness_association_data(pd.DataFrame({"a": [1, 2, 3]}))

    assert result["status"] == "insufficient_columns"
    assert result["data"].empty


def test_missingness_association_caps_rows_and_columns() -> None:
    df = pd.DataFrame(
        {f"c{i}": [None if row % (i + 2) else 1.0 for row in range(500)] for i in range(6)}
    )

    result = _missingness_association_data(df, max_rows=50, max_columns=3)

    assert result["rows_used"] == 50
    assert result["row_sampled"] is True
    assert result["columns_displayed"] <= 3
    assert result["column_truncated"] is True


def test_missingness_association_pairs_are_capped_and_deterministic() -> None:
    df = pd.DataFrame(
        {f"c{i}": [None if row % (i + 2) else 1.0 for row in range(200)] for i in range(8)}
    )

    first = _missingness_association_data(df, top_n=3)
    second = _missingness_association_data(df, top_n=3)

    assert len(first["pairs"]) == 3
    pd.testing.assert_frame_equal(first["pairs"], second["pairs"])


# ── ranked relationship pairs ────────────────────────────────────────────────


def test_ranked_pairs_drop_the_diagonal_and_mirrored_duplicates() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [2.0, 4.0, 6.0, 8.0, 10.0],
            "c": [5.0, 3.0, 4.0, 1.0, 2.0],
        }
    )

    pairs = _correlation_heatmap_data(df)["pairs"]

    assert len(pairs) == 3  # 3 columns -> exactly 3 unordered pairs
    seen = {frozenset((row["column_x"], row["column_y"])) for _, row in pairs.iterrows()}
    assert len(seen) == 3
    assert all(row["column_x"] != row["column_y"] for _, row in pairs.iterrows())


def test_ranked_pairs_preserve_sign_and_rank_by_absolute_strength() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [5.0, 4.0, 3.0, 2.0, 1.0],
            "c": [1.0, 3.0, 2.0, 5.0, 4.0],
        }
    )

    pairs = _correlation_heatmap_data(df)["pairs"]

    assert pairs.iloc[0]["correlation"] == pytest.approx(-1.0)
    assert pairs["abs_correlation"].tolist() == sorted(
        pairs["abs_correlation"].tolist(), reverse=True
    )


def test_ranked_pairs_are_capped_and_skip_undefined_cells() -> None:
    matrix = pd.DataFrame(
        [[1.0, 0.5, float("nan")], [0.5, 1.0, 0.2], [float("nan"), 0.2, 1.0]],
        index=["a", "b", "c"],
        columns=["a", "b", "c"],
    )

    ranked = _ranked_matrix_pairs(matrix, top_n=1)

    assert len(ranked) == 1
    assert {ranked.iloc[0]["column_x"], ranked.iloc[0]["column_y"]} == {"a", "b"}


def test_ranked_pairs_empty_matrix_returns_empty_frame() -> None:
    assert _ranked_matrix_pairs(pd.DataFrame()).empty


# ── explicit numeric-correlation column selection ────────────────────────────


def _wide_numeric_frame(columns: int = 25) -> pd.DataFrame:
    return pd.DataFrame({f"n{i}": [float(i + row) for row in range(6)] for i in range(columns)})


def test_numeric_correlation_default_selection_is_the_first_capped_columns() -> None:
    df = _wide_numeric_frame()

    selected = _numeric_correlation_columns(df)

    assert selected == [f"n{i}" for i in range(NUMERIC_CORRELATION_MAX_COLUMNS)]


def test_numeric_correlation_explicit_selection_is_honored_and_capped() -> None:
    df = _wide_numeric_frame()

    selected = _numeric_correlation_columns(df, [f"n{i}" for i in range(24, 10, -1)])

    assert selected[0] == "n24"
    assert len(selected) <= NUMERIC_CORRELATION_MAX_COLUMNS


def test_numeric_correlation_selection_drops_unknown_and_non_numeric_names() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0], "m": [3.0, 4.0], "c": ["a", "b"]})

    assert _numeric_correlation_columns(df, ["n", "c", "missing"]) == ["n"]
    # An entirely unusable selection falls back to the deterministic default.
    assert _numeric_correlation_columns(df, ["c", "missing"]) == ["n", "m"]


def test_correlation_heatmap_honors_the_explicit_selection() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [3.0, 2.0, 1.0], "c": [1.0, 4.0, 9.0]})

    result = _correlation_heatmap_data(df, selected_columns=["a", "c"])

    assert result["status"] == "ok"
    assert result["selected"] is True
    assert list(result["matrix"].columns) == ["a", "c"]


def test_correlation_methods_remain_supported_with_selection() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0], "b": [1.0, 4.0, 9.0, 16.0]})

    for method in ("pearson", "spearman", "kendall"):
        result = _correlation_heatmap_data(df, method=method, selected_columns=["a", "b"])
        assert result["status"] == "ok"
        assert result["method"] == method


# ── categorical association ──────────────────────────────────────────────────


def _assoc_frame(rows: int = 60) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "x": ["a" if i % 2 else "b" for i in range(rows)],
            "y": ["a" if i % 2 else "b" for i in range(rows)],
            "z": ["p" if i % 3 else "q" for i in range(rows)],
        }
    )


def test_categorical_association_is_symmetric_and_bounded_to_unit_interval() -> None:
    result = _categorical_association_data(_assoc_frame())

    assert result["status"] == "ok"
    matrix = result["matrix"]
    pd.testing.assert_frame_equal(matrix, matrix.T)
    assert matrix.to_numpy().min() >= 0.0
    assert matrix.to_numpy().max() <= 1.0


def test_categorical_association_diagonal_is_one() -> None:
    matrix = _categorical_association_data(_assoc_frame())["matrix"]

    assert all(matrix.iloc[i, i] == pytest.approx(1.0) for i in range(matrix.shape[0]))


def test_categorical_association_detects_a_perfect_dependency() -> None:
    result = _categorical_association_data(_assoc_frame())

    assert result["matrix"].loc["x", "y"] == pytest.approx(1.0)
    top = result["pairs"].iloc[0]
    assert {top["column_x"], top["column_y"]} == {"x", "y"}


def test_categorical_association_independent_columns_score_near_zero() -> None:
    df = pd.DataFrame(
        {
            "x": ["a", "a", "b", "b"] * 25,
            "y": ["p", "q", "p", "q"] * 25,
        }
    )

    result = _categorical_association_data(df)

    assert result["matrix"].loc["x", "y"] == pytest.approx(0.0, abs=1e-6)


def test_categorical_association_reports_structured_unavailable_reasons() -> None:
    df = pd.DataFrame(
        {
            "constant": ["same"] * 40,
            "empty": pd.Series([None] * 40, dtype="object"),
            "identifier": [f"id-{i}" for i in range(40)],
            "x": ["a" if i % 2 else "b" for i in range(40)],
            "y": ["p" if i % 3 else "q" for i in range(40)],
        }
    )

    result = _categorical_association_data(df)

    reasons = {entry["column"]: entry["reason"] for entry in result["unavailable"]}
    assert reasons["constant"] == "constant"
    assert reasons["empty"] == "empty"
    assert reasons["identifier"] == "near_unique"
    assert list(result["matrix"].columns) == ["x", "y"]


def test_categorical_association_caps_columns_and_flags_the_overflow() -> None:
    df = pd.DataFrame(
        {f"c{i}": ["a" if row % (i + 2) else "b" for row in range(40)] for i in range(12)}
    )

    result = _categorical_association_data(df, max_columns=3)

    assert result["columns_displayed"] == 3
    reasons = {entry["reason"] for entry in result["unavailable"]}
    assert "column_cap" in reasons


def test_categorical_association_default_column_cap_is_bounded() -> None:
    df = pd.DataFrame(
        {f"c{i}": ["a" if row % (i + 2) else "b" for row in range(40)] for i in range(12)}
    )

    result = _categorical_association_data(df)

    assert result["columns_displayed"] <= CATEGORICAL_ASSOC_MAX_COLUMNS


def test_categorical_association_caps_rows_and_marks_sample_derived_output() -> None:
    rows = CATEGORICAL_ASSOC_MAX_ROWS + 500
    df = pd.DataFrame(
        {
            "x": ["a" if i % 2 else "b" for i in range(rows)],
            "y": ["p" if i % 3 else "q" for i in range(rows)],
        }
    )

    result = _categorical_association_data(df)

    assert result["rows_used"] <= CATEGORICAL_ASSOC_MAX_ROWS
    assert result["row_sampled"] is True
    assert result["source_rows"] == rows


def test_categorical_association_insufficient_columns_is_safe() -> None:
    result = _categorical_association_data(pd.DataFrame({"only": ["a", "b", "c"]}))

    assert result["status"] == "insufficient_columns"
    assert result["data"].empty


def test_categorical_association_ranked_pairs_are_deterministic_and_capped() -> None:
    df = pd.DataFrame(
        {f"c{i}": ["a" if row % (i + 2) else "b" for row in range(60)] for i in range(6)}
    )

    first = _categorical_association_data(df, top_n=4)
    second = _categorical_association_data(df, top_n=4)

    assert len(first["pairs"]) == 4
    pd.testing.assert_frame_equal(first["pairs"], second["pairs"])


def test_categorical_association_does_not_mutate_input() -> None:
    df = _assoc_frame()
    before = df.copy(deep=True)

    _categorical_association_data(df)

    pd.testing.assert_frame_equal(df, before)


def test_categorical_association_never_reports_significance() -> None:
    result = _categorical_association_data(_assoc_frame())

    keys = {str(key).lower() for key in result}
    assert not any("p_value" in key or "chi" in key or "significan" in key for key in keys)


def test_capped_levels_folds_the_tail_into_other_deterministically() -> None:
    column = pd.Series(["top"] * 30 + [f"tail-{i}" for i in range(30)])

    capped = _capped_levels(column, max_levels=3, missing_label="(missing)")

    assert set(capped.unique()) <= {"top", "tail-0", "tail-1", "(other)"}
    assert int(capped.nunique()) <= 4
    assert list(capped.index) == list(range(len(column)))


def test_capped_levels_keeps_missing_as_an_explicit_bucket() -> None:
    column = pd.Series(["a", None, "b", None])

    capped = _capped_levels(column, max_levels=CATEGORICAL_ASSOC_MAX_LEVELS, missing_label="(m)")

    assert "(m)" in set(capped.unique())


def test_cramers_v_returns_none_for_degenerate_tables() -> None:
    constant = pd.Series(["a", "a", "a", "a"])
    varying = pd.Series(["p", "q", "p", "q"])

    assert _cramers_v(constant, varying) is None
    assert _cramers_v(pd.Series([], dtype="object"), pd.Series([], dtype="object")) is None


# ── purity: no framework, filesystem, state, or network coupling ─────────────

_PURE_BUILDERS = (
    _capped_levels,
    _categorical_association_data,
    _cramers_v,
    _deterministic_row_positions,
    _missingness_association_data,
    _missingness_pattern_data,
    _numeric_correlation_columns,
    _pareto_category_data,
    _qq_normal_data,
    _ranked_matrix_pairs,
)

_FORBIDDEN_IN_BUILDERS = (
    "streamlit",
    "session_state",
    "st.",
    "open(",
    "Path(",
    "read_csv",
    "to_csv",
    "requests",
    "urlopen",
    "random",
)

_FORBIDDEN_INFERENCE_TOKENS = ("p_value", "pvalue", "significan", "hypothesis", "reject")


def _executable_source(builder: object) -> str:
    """Return a builder's source with its docstring removed.

    Docstrings deliberately *disclaim* p-values and significance, so the code
    itself — not the prose about it — is what these contracts inspect.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(builder)))  # type: ignore[arg-type]
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)
    body = function.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return "\n".join(ast.unparse(node) for node in body)


@pytest.mark.parametrize("builder", _PURE_BUILDERS, ids=lambda fn: fn.__name__)
def test_visual_discovery_builders_stay_framework_free(builder: object) -> None:
    source = _executable_source(builder)
    for token in _FORBIDDEN_IN_BUILDERS:
        assert token not in source, f"{builder} must not reference {token}"


@pytest.mark.parametrize("builder", _PURE_BUILDERS, ids=lambda fn: fn.__name__)
def test_visual_discovery_builders_never_compute_inference(builder: object) -> None:
    source = _executable_source(builder).lower()
    for token in _FORBIDDEN_INFERENCE_TOKENS:
        assert token not in source, f"{builder} must not compute {token}"


def test_eda_module_imports_no_streamlit_or_scipy_at_module_level() -> None:
    """Importing the EDA builder module must not pull in Streamlit or SciPy.

    Only top-level statements are inspected: the module keeps one documented
    *lazy* Streamlit import inside the cached-loader helper, which is precisely
    what makes the pure builders importable outside a Streamlit runtime.
    """
    module = inspect.getmodule(_qq_normal_data)
    assert module is not None
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    assert "scipy" not in imported
    assert "streamlit" not in imported
