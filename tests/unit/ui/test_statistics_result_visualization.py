"""Contract tests for the Statistics Lab result-evidence builders and guidance.

Two Streamlit-free tiers are pinned here:

* ``services.statistics_visualization`` — deterministic, bounded chart-data
  builders that never execute a statistical test, never mutate their input, and
  return a typed unavailable state instead of fabricating or zero-filling a
  value that the result did not produce;
* ``services.statistics_guidance`` — deterministic interpretation structures that
  preserve every value and direction the result reported, keep the p-value from
  dominating, and never emit an equivalence, causal, or business claim.

All fixtures are synthetic; no dataset, screenshot, or file fixture is added.
"""

from __future__ import annotations

import ast
import inspect
from typing import Any

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.services import statistics_guidance as guide
from data_quality_toolkit.adapters.ui.services import statistics_visualization as viz

# ── structural rules ─────────────────────────────────────────────────────────

_FORBIDDEN_IMPORT_PREFIXES = (
    "streamlit",
    "requests",
    "urllib",
    "socket",
    "http",
    "data_quality_toolkit.api",
    "data_quality_toolkit.domain",
    "data_quality_toolkit.adapters.ui.services.statistics",
    "data_quality_toolkit.adapters.ui.state",
)


def _imported_modules(module: Any) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module", [viz, guide], ids=["visualization", "guidance"])
def test_builder_tier_imports_no_framework_domain_or_io_module(module: Any) -> None:
    imported = _imported_modules(module)
    offenders = [
        name
        for name in imported
        for prefix in _FORBIDDEN_IMPORT_PREFIXES
        if name == prefix or name.startswith(f"{prefix}.")
    ]
    assert offenders == []


@pytest.mark.parametrize("module", [viz, guide], ids=["visualization", "guidance"])
def test_builder_tier_touches_no_state_filesystem_or_randomness(module: Any) -> None:
    source = inspect.getsource(module)
    for marker in (
        "import streamlit",
        "session_state",
        "import random",
        "np.random",
        "open(",
        "Path(",
        "run_statistical_test",
        "_api_run_statistical_test",
    ):
        assert marker not in source, f"{module.__name__} must not reference {marker!r}"


def test_bounds_are_named_constants_with_the_admitted_ceilings() -> None:
    assert viz.RESULT_CHART_MAX_ROWS == 5_000
    assert viz.PAIRED_PLOT_MAX_PAIRS == 500
    assert viz.PAIRED_LINE_DISPLAY_MAX == 100
    assert viz.CONTINGENCY_MAX_ROWS == 20
    assert viz.CONTINGENCY_MAX_COLUMNS == 20
    assert viz.CONTINGENCY_MAX_CELLS == 400
    assert viz.GOF_MAX_CATEGORIES == 40
    assert viz.DISTRIBUTION_CURVE_MAX_POINTS == 401
    assert viz.POWER_CURVE_MAX_POINTS == 101
    assert viz.CI_PLOT_MAX_ESTIMATES == 50
    assert guide.GUIDANCE_MAX_ITEMS == 8
    assert guide.LIMITATIONS_MAX_ITEMS == 8


def test_deterministic_positions_never_sample_randomly() -> None:
    assert viz.deterministic_positions(5, 10) == [0, 1, 2, 3, 4]
    first = viz.deterministic_positions(1_000, 10)
    assert first == viz.deterministic_positions(1_000, 10)
    assert len(first) <= 10
    assert first == sorted(first)


def test_safe_label_bounds_text_and_strips_control_characters() -> None:
    assert viz.safe_label("a\nb") == "ab"
    assert viz.safe_label("") == "(blank)"
    assert len(viz.safe_label("x" * 500)) == viz.LABEL_MAX_TEXT


# ── chi-square goodness of fit ───────────────────────────────────────────────


def _gof_result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "ok",
        "column": "cat",
        "expected_mode": "equal",
        "category_count": 3,
        "valid_rows": 100,
        "excluded_rows": 0,
        "statistic": 2.0,
        "p_value": 0.3679,
        "alpha": 0.05,
        "reject_null": False,
        "categories": [
            {
                "category": "a",
                "observed": 30,
                "expected_proportion": 1 / 3,
                "expected_count": 100 / 3,
            },
            {
                "category": "b",
                "observed": 30,
                "expected_proportion": 1 / 3,
                "expected_count": 100 / 3,
            },
            {
                "category": "c",
                "observed": 40,
                "expected_proportion": 1 / 3,
                "expected_count": 100 / 3,
            },
        ],
    }
    result.update(overrides)
    return result


def test_gof_evidence_reports_observed_expected_difference_and_contribution() -> None:
    evidence = viz.build_gof_evidence(_gof_result())

    assert evidence["status"] == "ok"
    data = evidence["data"]
    assert list(data["category"]) == ["a", "b", "c"]
    assert list(data["observed"]) == [30, 30, 40]
    assert list(data["expected"]) == pytest.approx([100 / 3] * 3, rel=1e-6)
    assert list(data["difference"]) == pytest.approx([-10 / 3, -10 / 3, 20 / 3], rel=1e-6)
    assert list(data["contribution"]) == pytest.approx([1 / 3, 1 / 3, 4 / 3], rel=1e-5)
    assert list(data["contribution_share"]) == pytest.approx([1 / 6, 1 / 6, 2 / 3], rel=1e-5)
    assert evidence["total_contribution"] == pytest.approx(2.0, rel=1e-5)
    assert evidence["contribution_available"] is True
    assert evidence["sample_size"] == 100


def test_gof_evidence_marks_invalid_expected_counts_unavailable_without_zero_filling() -> None:
    result = _gof_result(
        categories=[
            {"category": "a", "observed": 30, "expected_count": 0.0},
            {"category": "b", "observed": 70, "expected_count": 70.0},
        ]
    )

    evidence = viz.build_gof_evidence(result)

    assert evidence["status"] == "ok"
    assert evidence["contribution_available"] is False
    assert evidence["total_contribution"] is None
    contributions = list(evidence["data"]["contribution"])
    assert pd.isna(contributions[0])  # unavailable, never coerced to zero
    assert contributions[1] == pytest.approx(0.0)
    assert all(pd.isna(share) for share in evidence["data"]["contribution_share"])


def test_gof_evidence_caps_categories_and_preserves_result_order() -> None:
    categories = [
        {"category": f"c{index:03d}", "observed": index + 1, "expected_count": 10.0}
        for index in range(120)
    ]

    evidence = viz.build_gof_evidence(_gof_result(categories=categories, category_count=120))

    assert len(evidence["data"]) == viz.GOF_MAX_CATEGORIES
    assert evidence["truncated"] is True
    assert evidence["category_count"] == 120
    assert evidence["displayed_categories"] == viz.GOF_MAX_CATEGORIES
    assert list(evidence["data"]["category"])[:3] == ["c000", "c001", "c002"]


def test_gof_evidence_requires_a_completed_result() -> None:
    evidence = viz.build_gof_evidence(_gof_result(status="unavailable"))

    assert evidence["status"] == "unavailable"
    assert evidence["data"].empty
    assert "goodness-of-fit" in str(evidence["reason"])


def test_gof_evidence_does_not_mutate_the_result() -> None:
    result = _gof_result()
    before = repr(result)

    viz.build_gof_evidence(result)

    assert repr(result) == before


# ── chi-square contingency ───────────────────────────────────────────────────


def _contingency_result(**overrides: Any) -> dict[str, Any]:
    cells = [
        {"row_category": "A", "col_category": "X", "observed": 30, "expected": 20.0},
        {"row_category": "A", "col_category": "Y", "observed": 10, "expected": 20.0},
        {"row_category": "B", "col_category": "X", "observed": 10, "expected": 20.0},
        {"row_category": "B", "col_category": "Y", "observed": 30, "expected": 20.0},
    ]
    result: dict[str, Any] = {
        "status": "ok",
        "first_column": "left",
        "second_column": "right",
        "row_labels": ["A", "B"],
        "col_labels": ["X", "Y"],
        "row_category_count": 2,
        "col_category_count": 2,
        "valid_rows": 80,
        "excluded_rows": 0,
        "statistic": 20.0,
        "p_value": 0.0000076,
        "alpha": 0.05,
        "reject_null": True,
        "cells": cells,
    }
    result.update(overrides)
    return result


def test_contingency_evidence_computes_signed_residual_and_contribution() -> None:
    evidence = viz.build_contingency_evidence(_contingency_result())

    assert evidence["status"] == "ok"
    data = evidence["data"]
    assert list(data["residual"]) == pytest.approx(
        [10 / 20**0.5, -10 / 20**0.5, -10 / 20**0.5, 10 / 20**0.5], rel=1e-6
    )
    assert list(data["contribution"]) == pytest.approx([5.0, 5.0, 5.0, 5.0], rel=1e-6)
    assert list(data["direction"]) == [
        "observed above expected",
        "observed below expected",
        "observed below expected",
        "observed above expected",
    ]
    assert evidence["row_count"] == 2
    assert evidence["col_count"] == 2
    assert evidence["cell_count"] == 4


def test_contingency_ranked_cells_are_deterministic_and_bounded() -> None:
    evidence = viz.build_contingency_evidence(_contingency_result(), ranked_limit=2)
    again = viz.build_contingency_evidence(_contingency_result(), ranked_limit=2)

    ranked = evidence["ranked"]
    assert len(ranked) == 2
    pd.testing.assert_frame_equal(ranked, again["ranked"])
    # Equal magnitudes tie-break on the result's own cell order, never randomly.
    assert list(ranked["row_category"]) == ["A", "A"]
    assert list(ranked["col_category"]) == ["X", "Y"]


def test_contingency_zero_expected_cell_is_unavailable_not_zero() -> None:
    result = _contingency_result(
        cells=[
            {"row_category": "A", "col_category": "X", "observed": 5, "expected": 0.0},
            {"row_category": "A", "col_category": "Y", "observed": 5, "expected": 5.0},
            {"row_category": "B", "col_category": "X", "observed": 5, "expected": 5.0},
            {"row_category": "B", "col_category": "Y", "observed": 5, "expected": 5.0},
        ]
    )

    evidence = viz.build_contingency_evidence(result)

    residuals = list(evidence["data"]["residual"])
    assert pd.isna(residuals[0])  # unavailable, never coerced to zero
    assert evidence["data"]["direction"].iloc[0] is None
    assert evidence["residual_available"] is True


def test_contingency_sparse_expected_counts_are_reported_informationally() -> None:
    result = _contingency_result(
        cells=[
            {"row_category": "A", "col_category": "X", "observed": 2, "expected": 1.0},
            {"row_category": "A", "col_category": "Y", "observed": 2, "expected": 2.0},
            {"row_category": "B", "col_category": "X", "observed": 2, "expected": 3.0},
            {"row_category": "B", "col_category": "Y", "observed": 2, "expected": 9.0},
        ]
    )

    evidence = viz.build_contingency_evidence(result)

    assert evidence["sparse_expected"] is True
    assert evidence["low_expected_cells"] == 3
    assert evidence["min_expected"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("rows", "cols"),
    [(21, 2), (2, 21), (20, 21)],
    ids=["too-many-rows", "too-many-columns", "too-many-cells"],
)
def test_contingency_out_of_bounds_table_returns_unavailable_and_drops_nothing(
    rows: int, cols: int
) -> None:
    cells = [
        {
            "row_category": f"r{row}",
            "col_category": f"c{col}",
            "observed": 1,
            "expected": 1.0,
        }
        for row in range(rows)
        for col in range(cols)
    ]
    result = _contingency_result(
        cells=cells,
        row_labels=[f"r{row}" for row in range(rows)],
        col_labels=[f"c{col}" for col in range(cols)],
        row_category_count=rows,
        col_category_count=cols,
    )

    evidence = viz.build_contingency_evidence(result)

    assert evidence["status"] == "unavailable"
    assert evidence["data"].empty
    assert "bounded at" in str(evidence["reason"])


def test_contingency_evidence_requires_a_completed_result() -> None:
    evidence = viz.build_contingency_evidence(_contingency_result(status="insufficient_data"))
    assert evidence["status"] == "unavailable"


# ── estimates and intervals ──────────────────────────────────────────────────


def test_estimate_evidence_carries_point_interval_and_reference() -> None:
    evidence = viz.build_estimate_interval_evidence(
        [
            {
                "label": "Mean",
                "estimate": 10.0,
                "lower": 8.5,
                "upper": 11.5,
                "confidence": 0.95,
                "n": 25,
            }
        ],
        reference=9.0,
    )

    assert evidence["status"] == "ok"
    row = evidence["data"].iloc[0]
    assert row["estimate"] == pytest.approx(10.0)
    assert row["lower"] == pytest.approx(8.5)
    assert row["upper"] == pytest.approx(11.5)
    assert bool(row["interval_available"]) is True
    assert evidence["reference"] == pytest.approx(9.0)
    assert evidence["reference_available"] is True


@pytest.mark.parametrize(
    "entry",
    [
        {"label": "Mean", "estimate": 10.0, "lower": None, "upper": 11.5},
        {"label": "Mean", "estimate": 10.0, "lower": 11.5, "upper": 8.5},
        {"label": "Mean", "estimate": 10.0},
    ],
    ids=["partial", "inverted", "absent"],
)
def test_estimate_evidence_never_maps_a_missing_interval_to_zero(entry: dict[str, Any]) -> None:
    evidence = viz.build_estimate_interval_evidence([entry])

    row = evidence["data"].iloc[0]
    assert bool(row["interval_available"]) is False
    assert row["lower"] is None
    assert row["upper"] is None
    assert evidence["intervals_available"] is False


def test_estimate_evidence_omits_a_non_finite_reference_line() -> None:
    evidence = viz.build_estimate_interval_evidence(
        [{"label": "Mean", "estimate": 1.0, "lower": 0.0, "upper": 2.0}],
        reference=float("nan"),
    )

    assert evidence["reference_available"] is False
    assert evidence["reference"] is None


def test_estimate_evidence_without_a_finite_point_is_unavailable() -> None:
    evidence = viz.build_estimate_interval_evidence([{"label": "Mean", "estimate": None}])

    assert evidence["status"] == "unavailable"
    assert evidence["data"].empty


def test_estimate_evidence_is_capped() -> None:
    estimates = [{"label": f"e{i}", "estimate": float(i)} for i in range(200)]

    evidence = viz.build_estimate_interval_evidence(estimates)

    assert len(evidence["data"]) == viz.CI_PLOT_MAX_ESTIMATES
    assert evidence["truncated"] is True


# ── paired evidence ──────────────────────────────────────────────────────────


def test_paired_evidence_keeps_direction_counts_and_anonymous_positions() -> None:
    before = [1.0, 2.0, float("nan"), 4.0]
    after = [0.5, 1.0, 3.0, float("nan")]

    evidence = viz.build_paired_evidence(before, after, total_rows=4)

    assert evidence["status"] == "ok"
    assert evidence["complete_pairs"] == 2
    assert evidence["excluded_rows"] == 2
    data = evidence["data"]
    assert list(data.columns) == ["pair", "before", "after", "difference"]
    assert list(data["pair"]) == [1, 2]
    assert list(data["difference"]) == pytest.approx([0.5, 1.0])
    assert evidence["difference_summary"]["median"] == pytest.approx(0.75)


def test_paired_evidence_never_exposes_a_source_row_index() -> None:
    before = [10.0, float("nan"), 30.0]
    after = [1.0, 5.0, 3.0]

    evidence = viz.build_paired_evidence(before, after, total_rows=3)

    # Row 1 was dropped; the surviving rows are renumbered from 1, not 0 and 2.
    assert list(evidence["data"]["pair"]) == [1, 2]


def test_paired_evidence_bounds_plotted_pairs_and_line_display() -> None:
    size = viz.PAIRED_PLOT_MAX_PAIRS * 4
    before = [float(index) for index in range(size)]
    after = [float(index) - 1.0 for index in range(size)]

    evidence = viz.build_paired_evidence(before, after)

    assert evidence["complete_pairs"] == size
    assert len(evidence["data"]) <= viz.PAIRED_PLOT_MAX_PAIRS
    assert evidence["truncated"] is True
    assert len(evidence["lines"]) <= viz.PAIRED_LINE_DISPLAY_MAX
    assert len(evidence["lines_long"]) == 2 * len(evidence["lines"])
    assert set(evidence["lines_long"]["measurement"]) == {"before", "after"}


def test_paired_evidence_reports_unavailable_when_no_pair_survives() -> None:
    evidence = viz.build_paired_evidence([float("nan")], [1.0], total_rows=1)

    assert evidence["status"] == "unavailable"
    assert evidence["complete_pairs"] == 0
    assert evidence["excluded_rows"] == 1


def test_paired_evidence_rejects_mismatched_lengths() -> None:
    assert viz.build_paired_evidence([1.0, 2.0], [1.0])["status"] == "unavailable"


def test_paired_evidence_does_not_mutate_inputs() -> None:
    before = [1.0, 2.0]
    after = [0.0, 1.0]

    viz.build_paired_evidence(before, after)

    assert before == [1.0, 2.0]
    assert after == [0.0, 1.0]


# ── proportions ──────────────────────────────────────────────────────────────


def test_proportion_evidence_reports_counts_denominators_and_difference() -> None:
    evidence = viz.build_proportion_evidence(
        [
            {"label": "1 [int]", "successes": 20, "total": 30, "proportion": 2 / 3},
            {"label": "1 [str]", "successes": 10, "total": 40, "proportion": 0.25},
        ],
        difference=2 / 3 - 0.25,
    )

    assert evidence["status"] == "ok"
    data = evidence["data"]
    # Collision-safe typed labels survive verbatim; nothing is merged by text.
    assert list(data["label"]) == ["1 [int]", "1 [str]"]
    assert list(data["successes"]) == [20, 10]
    assert list(data["total"]) == [30, 40]
    assert list(data["proportion"]) == pytest.approx([2 / 3, 0.25], rel=1e-6)
    assert evidence["difference_available"] is True
    assert evidence["difference"] == pytest.approx(2 / 3 - 0.25, rel=1e-6)
    assert evidence["intervals_available"] is False


def test_proportion_evidence_draws_whiskers_only_from_an_existing_interval() -> None:
    evidence = viz.build_proportion_evidence(
        [{"label": "yes", "successes": 5, "total": 10, "lower": 0.2, "upper": 0.8}]
    )

    assert evidence["intervals_available"] is True
    assert evidence["data"].iloc[0]["lower"] == pytest.approx(0.2)


def test_proportion_evidence_marks_a_reference_only_when_finite() -> None:
    with_reference = viz.build_proportion_evidence(
        [{"label": "yes", "successes": 5, "total": 10}], reference=0.5
    )
    without = viz.build_proportion_evidence(
        [{"label": "yes", "successes": 5, "total": 10}], reference=None
    )

    assert with_reference["reference_available"] is True
    assert without["reference_available"] is False


def test_proportion_evidence_rejects_a_zero_denominator() -> None:
    evidence = viz.build_proportion_evidence([{"label": "yes", "successes": 0, "total": 0}])

    assert evidence["status"] == "unavailable"
    assert evidence["data"].empty


# ── group comparison ─────────────────────────────────────────────────────────


def test_group_evidence_carries_sizes_centres_and_missing_intervals() -> None:
    evidence = viz.build_group_comparison_evidence(
        [
            {"group": "a", "n": 12, "center": 3.5},
            {"group": "b", "n": 9, "center": 4.5, "lower": 4.0, "upper": 5.0},
        ]
    )

    data = evidence["data"]
    assert list(data["group"]) == ["a", "b"]
    assert list(data["n"]) == [12, 9]
    assert list(data["interval_available"]) == [False, True]
    assert evidence["intervals_available"] is True


def test_group_evidence_is_bounded_and_skips_non_finite_centres() -> None:
    groups = [{"group": f"g{i}", "n": 1, "center": float(i)} for i in range(120)]

    evidence = viz.build_group_comparison_evidence(groups)

    assert len(evidence["data"]) == viz.CI_PLOT_MAX_ESTIMATES
    assert evidence["truncated"] is True

    empty = viz.build_group_comparison_evidence([{"group": "a", "n": 1, "center": None}])
    assert empty["status"] == "unavailable"


# ── grids, distribution curves and power curves ──────────────────────────────


def test_parameter_grid_is_bounded_deterministic_and_guards_bad_bounds() -> None:
    grid = viz.build_parameter_grid(
        0.0, 10.0, points=5_000, maximum=viz.DISTRIBUTION_CURVE_MAX_POINTS
    )
    assert len(grid) == viz.DISTRIBUTION_CURVE_MAX_POINTS
    assert grid[0] == pytest.approx(0.0)
    assert grid[-1] == pytest.approx(10.0)
    assert grid == viz.build_parameter_grid(
        0.0, 10.0, points=5_000, maximum=viz.DISTRIBUTION_CURVE_MAX_POINTS
    )

    integers = viz.build_parameter_grid(0.0, 4.0, points=101, maximum=101, integer=True)
    assert integers == [0.0, 1.0, 2.0, 3.0, 4.0]

    assert viz.build_parameter_grid(float("nan"), 1.0, points=10, maximum=10) == []
    assert viz.build_parameter_grid(5.0, 1.0, points=10, maximum=10) == []


def test_distribution_curve_is_bounded_shaded_and_skips_undefined_points() -> None:
    def evaluate(value: float) -> dict[str, Any]:
        if value < 0:
            return {"status": "invalid_input", "value": None}
        return {"status": "ok", "value": value * 2.0}

    grid = [float(index) - 5.0 for index in range(1_000)]

    evidence = viz.build_distribution_curve(evaluate, grid, marker=2.0, shade_upper=2.0)

    assert evidence["status"] == "ok"
    assert len(evidence["data"]) <= viz.DISTRIBUTION_CURVE_MAX_POINTS
    assert evidence["truncated"] is True
    assert evidence["invalid_points"] > 0
    assert evidence["marker_available"] is True
    shaded = evidence["data"][evidence["data"]["shaded"]]
    assert bool((shaded["x"] <= 2.0).all())


def test_distribution_curve_without_a_usable_point_is_unavailable() -> None:
    evidence = viz.build_distribution_curve(
        lambda _value: {"status": "unavailable", "value": None}, [0.0, 1.0]
    )

    assert evidence["status"] == "unavailable"
    assert evidence["data"].empty
    assert evidence["invalid_points"] == 2


def test_power_curve_is_bounded_marks_the_selection_and_skips_invalid_points() -> None:
    def evaluate(value: float) -> dict[str, Any]:
        if value < 5:
            return {"status": "invalid_input", "reason": "n must be > 0"}
        return {"status": "ok", "power": min(1.0, value / 100.0)}

    grid = [float(index) for index in range(500)]

    evidence = viz.build_power_curve(evaluate, grid, selected=50.0)

    assert evidence["status"] == "ok"
    assert len(evidence["data"]) <= viz.POWER_CURVE_MAX_POINTS
    assert evidence["invalid_points"] > 0
    assert evidence["selected_available"] is True
    assert evidence["value_field"] == "power"


def test_power_curve_reads_an_alternative_value_field() -> None:
    evidence = viz.build_power_curve(
        lambda value: {"status": "ok", "n_per_group": int(value) * 2},
        [1.0, 2.0, 3.0],
        value_field="n_per_group",
    )

    assert list(evidence["data"]["value"]) == [2, 4, 6]


def test_curve_builders_survive_a_hostile_evaluator() -> None:
    def explode(_value: float) -> dict[str, Any]:
        raise RuntimeError("evaluator failed")

    assert viz.build_power_curve(explode, [1.0, 2.0])["status"] == "unavailable"
    assert viz.build_distribution_curve(explode, [1.0, 2.0])["status"] == "unavailable"


# ── guidance: structure, safety and wording ──────────────────────────────────


def _all_guidance_text(guidance: guide.ResultGuidance) -> str:
    return " ".join(f"{heading} {text}" for heading, text in guide.guidance_sections(guidance))


_GUIDANCE_CASES: dict[str, guide.ResultGuidance] = {
    "gof": guide.guidance_for_goodness_of_fit(_gof_result()),
    "independence": guide.guidance_for_contingency(_contingency_result()),
    "homogeneity": guide.guidance_for_contingency(
        {
            **_contingency_result(),
            "group_column": "population",
            "outcome_column": "response",
        },
        family="homogeneity",
    ),
    "interval": guide.guidance_for_interval(
        {
            "status": "ok",
            "method": "t",
            "confidence": 0.95,
            "point": 10.0,
            "lower": 8.5,
            "upper": 11.5,
            "n": 25,
        }
    ),
    "paired": guide.guidance_for_paired(
        {
            "status": "ok",
            "n_pairs": 20,
            "n_excluded_rows": 2,
            "p_value": 0.2,
            "alpha": 0.05,
            "reject_null": False,
            "alternative": "greater",
        },
        first="before",
        second="after",
    ),
    "proportion": guide.guidance_for_proportion(
        {
            "status": "ok",
            "outcome_column": "outcome",
            "success_label": "yes [str]",
            "observed_proportion": 0.7,
            "null_proportion": 0.5,
            "success_count": 70,
            "valid_rows": 100,
            "p_value": 0.0001,
            "alpha": 0.05,
            "reject_null": True,
            "alternative": "two-sided",
        }
    ),
    "two_group": guide.guidance_for_two_group(
        {
            "status": "ok",
            "metric": "value",
            "group_a": "a",
            "group_b": "b",
            "n_a": 10,
            "n_b": 12,
            "mean_a": 5.0,
            "mean_b": 4.0,
            "delta_mean": 1.0,
            "cohens_d": 0.4,
            "alpha": 0.05,
            "welch": {"p_value": 0.2, "significant": False},
            "mann_whitney": {"p_value": 0.3, "significant": False},
        }
    ),
    "multi_group": guide.guidance_for_multi_group(
        {
            "status": "ok",
            "metric": "value",
            "group_col": "grp",
            "n_groups": 3,
            "alpha": 0.05,
            "anova": {"p_value": 0.01, "significant": True},
            "kruskal": {"p_value": 0.02, "significant": True},
        }
    ),
    "effect": guide.guidance_for_effect_sizes(
        {
            "status": "ok",
            "group_a": "a",
            "group_b": "b",
            "confidence": 0.95,
            "cliffs_delta": 0.3,
            "cliffs_interpretation": "small",
            "hodges_lehmann": {"status": "ok", "estimate": 1.0, "lower": 0.2, "upper": 1.8},
        }
    ),
    "distribution": guide.guidance_for_distribution(
        {
            "status": "ok",
            "distribution": "Normal",
            "calculation": "CDF",
            "value": 0.84,
            "parameters": {"x": 1.0, "mu": 0.0, "sigma": 1.0},
        }
    ),
    "power": guide.guidance_for_power(
        {"status": "ok", "method": "normal_power_mean", "power": 0.8},
        analysis="Power — one-sample mean",
        alpha=0.05,
        alternative="two-sided",
    ),
    "assumptions": guide.guidance_for_assumptions(
        {
            "status": "ok",
            "checks": [
                {"name": "Normality", "status": "caution", "interpretation": "skewed"},
                {"name": "Equal variance", "status": "pass", "interpretation": "similar"},
            ],
        }
    ),
}


@pytest.mark.parametrize("name", sorted(_GUIDANCE_CASES))
def test_guidance_is_deterministic_and_structurally_complete(name: str) -> None:
    guidance = _GUIDANCE_CASES[name]

    assert isinstance(guidance, guide.ResultGuidance)
    assert guidance.family
    assert guidance.compared
    assert guidance.limitations
    assert guidance.do_not_conclude
    assert guidance.next_steps
    sections = guide.guidance_sections(guidance)
    assert sections == guide.guidance_sections(guidance)
    assert [heading for heading, _ in sections][0] == "What was compared"


@pytest.mark.parametrize("name", sorted(_GUIDANCE_CASES))
def test_guidance_never_uses_forbidden_wording(name: str) -> None:
    text = _all_guidance_text(_GUIDANCE_CASES[name]).lower()

    for phrase in guide.FORBIDDEN_GUIDANCE_PHRASES:
        assert phrase not in text, f"{name} guidance used forbidden wording {phrase!r}"


@pytest.mark.parametrize("name", sorted(_GUIDANCE_CASES))
def test_guidance_caps_every_list(name: str) -> None:
    guidance = _GUIDANCE_CASES[name]

    assert len(guidance.assumptions) <= guide.GUIDANCE_MAX_ITEMS
    assert len(guidance.limitations) <= guide.LIMITATIONS_MAX_ITEMS
    assert len(guidance.do_not_conclude) <= guide.GUIDANCE_MAX_ITEMS
    assert len(guidance.next_steps) <= guide.GUIDANCE_MAX_ITEMS
    assert len(guidance.unavailable) <= guide.GUIDANCE_MAX_ITEMS


def test_guidance_does_not_let_the_p_value_dominate() -> None:
    guidance = _GUIDANCE_CASES["proportion"]

    assert guidance.evidence is not None
    assert guidance.estimate is not None
    assert guidance.effect is not None
    assert "does not measure the size" in guidance.evidence
    populated = [
        value
        for value in (guidance.estimate, guidance.uncertainty, guidance.evidence, guidance.effect)
        if value
    ]
    assert len(populated) >= 3


def test_non_rejection_is_never_read_as_equivalence_or_absence_of_an_effect() -> None:
    guidance = _GUIDANCE_CASES["paired"]

    joined = " ".join(guidance.do_not_conclude).lower()
    assert "not rejecting the null is not evidence that the null holds" in joined
    assert "does not establish equivalence" in joined
    assert guidance.evidence is not None
    assert "is not below alpha" in guidance.evidence


def test_guidance_makes_no_causal_claim() -> None:
    for name in ("paired", "independence", "two_group", "proportion"):
        text = _all_guidance_text(_GUIDANCE_CASES[name]).lower()
        assert "does not establish cause" in text


def test_omnibus_guidance_refuses_a_pairwise_conclusion() -> None:
    guidance = _GUIDANCE_CASES["multi_group"]

    joined = " ".join(guidance.limitations + guidance.do_not_conclude).lower()
    assert "does not identify which groups differ" in joined
    assert "post-hoc" in joined
    assert "pairwise" in joined


def test_guidance_marks_missing_estimate_interval_and_effect_unavailable() -> None:
    guidance = guide.guidance_for_effect_sizes(
        {
            "status": "ok",
            "group_a": "a",
            "group_b": "b",
            "confidence": 0.95,
            "cliffs_delta": None,
            "hodges_lehmann": {"status": "unavailable", "estimate": None},
        }
    )

    assert guidance.estimate is None
    assert guidance.uncertainty is None
    assert guidance.effect is None
    assert "estimate" in guidance.unavailable
    assert "uncertainty" in guidance.unavailable
    assert "effect" in guidance.unavailable
    assert "hodges_lehmann_interval" in guidance.unavailable


def test_guidance_separates_evidence_from_practical_importance() -> None:
    for name in ("two_group", "proportion", "effect", "interval"):
        text = _all_guidance_text(_GUIDANCE_CASES[name]).lower()
        assert "domain judgement" in text or "smallest difference" in text


def test_assumption_guidance_stays_informational() -> None:
    guidance = _GUIDANCE_CASES["assumptions"]
    joined = " ".join(guidance.assumptions + guidance.do_not_conclude).lower()

    assert "never switch the selected test" in joined
    assert "compliance score" in joined
    assert "rules of thumb" in joined
    assert guidance.estimate is not None
    assert "Normality: caution" in guidance.estimate


def test_guidance_preserves_alternative_and_paired_direction() -> None:
    paired = _GUIDANCE_CASES["paired"]

    assert "before minus after" in paired.compared
    assert paired.evidence is not None
    assert "greater alternative" in paired.evidence


def test_chi_square_guidance_reports_no_directional_alternative() -> None:
    guidance = _GUIDANCE_CASES["gof"]

    assert guidance.evidence is not None
    assert "alternative" not in guidance.evidence


def test_homogeneity_guidance_stays_distinct_from_independence_framing() -> None:
    homogeneity = _all_guidance_text(_GUIDANCE_CASES["homogeneity"]).lower()

    assert "same outcome distribution" in homogeneity
    assert "which group differs" in homogeneity


def test_guidance_for_an_incomplete_result_is_explicitly_unavailable() -> None:
    guidance = guide.guidance_for_goodness_of_fit({"status": "unavailable"})

    assert "result" in guidance.unavailable
    assert guidance.estimate is None
    assert guidance.limitations


def test_guidance_reads_prepared_evidence_without_recomputing_the_test() -> None:
    result = _gof_result()
    evidence = viz.build_gof_evidence(result)

    guidance = guide.guidance_for_goodness_of_fit(result, evidence=evidence)

    assert guidance.effect is not None
    assert "Largest mismatch" in guidance.effect
    assert "c" in guidance.effect
    assert guidance.evidence is not None
    assert "0.3679" in guidance.evidence
