"""Tests for the pure Smart Data Overview preview service.

The service is framework-free: these tests never construct a Streamlit double,
never touch the filesystem, and use deterministic synthetic frames only. They
pin the documented role precedence, the named performance bounds, the
fact/heuristic/sample/unavailable evidence classification, record-strategy
determinism, and the purity guarantees (no mutation, no Streamlit, no IO).
"""

from __future__ import annotations

import ast
import inspect
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.services import smart_data_overview as sdo
from data_quality_toolkit.adapters.ui.services.smart_data_overview import (
    ANALYSIS_FULL,
    ANALYSIS_SAMPLE,
    DATETIME_TEXT_MIN_VALUES,
    EVIDENCE_FACT,
    EVIDENCE_HEURISTIC,
    EVIDENCE_LABELS,
    EVIDENCE_SAMPLE,
    EVIDENCE_UNAVAILABLE,
    IDENTIFIER_MIN_NON_NULL,
    MAX_CALLOUTS,
    MAX_CATEGORY_VALUES,
    MAX_CONTENT_COLUMNS,
    MAX_CONTENT_ROWS,
    MAX_GROUP_COLUMNS,
    MAX_RECORD_COLUMNS,
    MAX_RECORD_ROWS,
    MAX_RECORD_ROWS_PER_STRATEGY,
    MAX_RECORD_SCAN_ROWS,
    ROLE_CATEGORICAL,
    ROLE_DATETIME,
    ROLE_IDENTIFIER,
    ROLE_MEASURE,
    ROLE_OTHER,
    ROLE_PRECEDENCE,
    SEVERITY_ATTENTION,
    SEVERITY_NOTE,
    STRATEGY_EVEN_SPREAD,
    STRATEGY_FIRST_ROWS,
    STRATEGY_MOST_MISSING,
    WIDE_COLUMN_THRESHOLD,
    PreviewIdentity,
    build_smart_overview,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_for(df: pd.DataFrame) -> dict[str, Any]:
    """Build the same profile envelope shape the page already holds."""
    return {
        "rows": int(len(df)),
        "cols": int(df.shape[1]),
        "columns": [
            {
                "name": str(name),
                "dtype": str(df[name].dtype),
                "nulls": int(df[name].isna().sum()),
                "unique": int(df[name].nunique(dropna=True)),
            }
            for name in df.columns
        ],
    }


def _roles(overview: sdo.SmartOverview) -> dict[str, str]:
    return {signal.name: signal.role for signal in overview.displayed_signals}


def _signal(overview: sdo.SmartOverview, name: str) -> sdo.ColumnSignal:
    return next(s for s in overview.displayed_signals if s.name == name)


def _keys(overview: sdo.SmartOverview) -> list[str]:
    return [callout.key for callout in overview.callouts]


def _build(df: pd.DataFrame, **kwargs: Any) -> sdo.SmartOverview:
    return build_smart_overview(profile=_profile_for(df), frame=df, **kwargs)


# ---------------------------------------------------------------------------
# Role precedence
# ---------------------------------------------------------------------------


def test_role_precedence_order_is_documented_and_stable() -> None:
    assert ROLE_PRECEDENCE == (
        ROLE_IDENTIFIER,
        ROLE_DATETIME,
        ROLE_CATEGORICAL,
        ROLE_MEASURE,
        ROLE_OTHER,
    )


def test_each_column_receives_exactly_one_primary_role() -> None:
    df = pd.DataFrame(
        {
            "order_id": [f"O{i:03d}" for i in range(10)],
            "when": pd.to_datetime(["2024-01-01"] * 10),
            "segment": ["a", "b"] * 5,
            "amount": [float(i) for i in range(10)],
        }
    )
    overview = _build(df)
    names = [signal.name for signal in overview.displayed_signals]
    assert sorted(names) == sorted(df.columns)
    assert len(names) == len(set(names))


def test_groups_follow_role_precedence_order() -> None:
    df = pd.DataFrame(
        {
            "amount": [float(i) for i in range(10)],
            "segment": ["a", "b"] * 5,
            "when": pd.to_datetime(["2024-01-01"] * 10),
            "order_id": [f"O{i:03d}" for i in range(10)],
        }
    )
    overview = _build(df)
    ordered = [group.role for group in overview.groups]
    assert ordered == [role for role in ROLE_PRECEDENCE if role in ordered]
    assert ordered[0] == ROLE_IDENTIFIER


# ---------------------------------------------------------------------------
# Identifier versus measure
# ---------------------------------------------------------------------------


def test_named_unique_integer_is_identifier_not_measure() -> None:
    df = pd.DataFrame({"customer_id": list(range(100, 120))})
    assert _roles(_build(df))["customer_id"] == ROLE_IDENTIFIER
    assert _signal(_build(df), "customer_id").role_evidence == EVIDENCE_HEURISTIC


def test_unique_continuous_float_is_a_measure_not_an_identifier() -> None:
    """High uniqueness alone must never relabel a continuous measure as a key."""
    df = pd.DataFrame({"revenue_id": [float(i) * 1.5 for i in range(20)]})
    assert _roles(_build(df))["revenue_id"] == ROLE_MEASURE


def test_unique_integer_without_a_name_hint_stays_a_measure() -> None:
    df = pd.DataFrame({"reading": list(range(100, 120))})
    assert _roles(_build(df))["reading"] == ROLE_MEASURE


def test_unique_free_text_without_a_name_hint_is_not_an_identifier() -> None:
    df = pd.DataFrame({"notes": [f"free text {i}" for i in range(20)]})
    assert _roles(_build(df))["notes"] == ROLE_OTHER


def test_named_column_below_the_non_null_floor_is_not_an_identifier() -> None:
    rows = IDENTIFIER_MIN_NON_NULL - 1
    df = pd.DataFrame({"order_id": list(range(rows))})
    assert _roles(_build(df))["order_id"] != ROLE_IDENTIFIER


def test_named_column_with_repeated_values_is_not_an_identifier() -> None:
    df = pd.DataFrame({"order_id": ["a", "a", "b", "b", "c", "c", "d", "d"]})
    assert _roles(_build(df))["order_id"] != ROLE_IDENTIFIER


# ---------------------------------------------------------------------------
# Categorical and boolean
# ---------------------------------------------------------------------------


def test_boolean_and_category_dtypes_are_categorical_by_fact_not_measures() -> None:
    df = pd.DataFrame(
        {
            "active": [True, False] * 5,
            "tier": pd.Series(["gold", "silver"] * 5, dtype="category"),
        }
    )
    overview = _build(df)
    assert _roles(overview)["active"] == ROLE_CATEGORICAL
    assert _roles(overview)["tier"] == ROLE_CATEGORICAL
    assert _signal(overview, "active").role_evidence == EVIDENCE_FACT
    assert _signal(overview, "tier").role_evidence == EVIDENCE_FACT


def test_repeating_low_cardinality_text_is_categorical_by_heuristic() -> None:
    df = pd.DataFrame({"segment": ["a", "b", "c"] * 10})
    overview = _build(df)
    assert _roles(overview)["segment"] == ROLE_CATEGORICAL
    assert _signal(overview, "segment").role_evidence == EVIDENCE_HEURISTIC


def test_text_above_the_category_bound_is_unclassified() -> None:
    values = [f"v{i}" for i in range(MAX_CATEGORY_VALUES + 5)]
    df = pd.DataFrame({"label": values + values})
    assert _roles(_build(df))["label"] == ROLE_OTHER


def test_unknown_distinct_count_marks_text_as_not_evaluated() -> None:
    """An approximate profile without unique counts must not guess a role."""
    profile = {
        "rows": 100,
        "cols": 1,
        "columns": [{"name": "name", "dtype": "object", "nulls": 0}],
    }
    overview = build_smart_overview(profile=profile, analysis_mode=ANALYSIS_SAMPLE)
    assert _roles(overview)["name"] == ROLE_OTHER
    assert _signal(overview, "name").role_evidence == EVIDENCE_UNAVAILABLE


# ---------------------------------------------------------------------------
# Datetime handling
# ---------------------------------------------------------------------------


def test_actual_datetime_dtype_is_a_factual_datetime_role() -> None:
    df = pd.DataFrame({"created": pd.to_datetime([f"2024-01-{i + 1:02d}" for i in range(10)])})
    overview = _build(df)
    assert _roles(overview)["created"] == ROLE_DATETIME
    assert _signal(overview, "created").role_evidence == EVIDENCE_FACT


def test_timezone_aware_datetime_dtype_is_still_a_datetime_role() -> None:
    stamps = pd.to_datetime([f"2024-01-{i + 1:02d}" for i in range(10)], utc=True)
    df = pd.DataFrame({"created": stamps})
    assert _roles(_build(df))["created"] == ROLE_DATETIME


def test_timedelta_dtype_is_not_reported_as_a_datetime_field() -> None:
    df = pd.DataFrame({"elapsed": pd.to_timedelta([f"{i} days" for i in range(10)])})
    assert _roles(_build(df))["elapsed"] != ROLE_DATETIME


def test_datetime_strings_are_detected_as_a_heuristic_suggestion() -> None:
    df = pd.DataFrame({"signup": [f"2024-01-{i + 1:02d}" for i in range(10)]})
    overview = _build(df)
    assert _roles(overview)["signup"] == ROLE_DATETIME
    assert _signal(overview, "signup").role_evidence == EVIDENCE_HEURISTIC


def test_bare_numeric_strings_are_never_read_as_dates() -> None:
    df = pd.DataFrame({"signup": [str(20240100 + i) for i in range(10)]})
    assert _roles(_build(df))["signup"] != ROLE_DATETIME


def test_too_few_values_block_datetime_string_detection() -> None:
    count = DATETIME_TEXT_MIN_VALUES - 1
    df = pd.DataFrame({"signup": [f"2024-01-{i + 1:02d}" for i in range(count)]})
    assert _roles(_build(df))["signup"] != ROLE_DATETIME


def test_mostly_unparseable_text_is_not_reported_as_dates() -> None:
    values = [f"2024-01-{i + 1:02d}" for i in range(3)] + [f"note {i}" for i in range(17)]
    df = pd.DataFrame({"signup": values})
    assert _roles(_build(df))["signup"] != ROLE_DATETIME


def test_datetime_detection_reads_only_the_bounded_head() -> None:
    """Values beyond the row bound cannot change a content heuristic."""
    dates = [f"2024-01-{(i % 28) + 1:02d}" for i in range(MAX_CONTENT_ROWS)]
    junk = [f"junk {i}" for i in range(MAX_CONTENT_ROWS)]
    detected = pd.DataFrame({"signup": dates + junk})
    hidden = pd.DataFrame({"signup": junk + dates})
    assert _roles(_build(detected))["signup"] == ROLE_DATETIME
    assert _roles(_build(hidden))["signup"] != ROLE_DATETIME


# ---------------------------------------------------------------------------
# Degenerate frames
# ---------------------------------------------------------------------------


def test_all_null_column_is_safely_classified_without_raising() -> None:
    df = pd.DataFrame({"empty": [None] * 10})
    overview = _build(df)
    signal = _signal(overview, "empty")
    assert signal.role == ROLE_OTHER
    assert signal.missing_pct == 100.0
    assert signal.unique_pct is None


def test_zero_row_frame_reports_an_empty_dataset_callout() -> None:
    df = pd.DataFrame({"a": pd.Series(dtype="float64")})
    overview = _build(df)
    assert overview.rows == 0
    assert "empty_dataset" in _keys(overview)
    assert overview.selection.available is False


def test_zero_column_frame_reports_a_no_columns_callout() -> None:
    overview = _build(pd.DataFrame())
    assert overview.columns == 0
    assert overview.groups == ()
    assert "no_columns" in _keys(overview)
    assert overview.selection.available is False


def test_mixed_type_object_column_is_handled_safely() -> None:
    df = pd.DataFrame({"mixed": [1, "a", None, 2.5, "b"] * 4})
    overview = _build(df)
    assert _roles(overview)["mixed"] in set(ROLE_PRECEDENCE)


def test_builder_without_any_input_returns_a_safe_empty_model() -> None:
    overview = build_smart_overview()
    assert overview.rows is None
    assert overview.columns == 0
    assert overview.groups == ()
    assert overview.group_summary() == "No column groups available."
    assert overview.selection.available is False


def test_frame_only_input_derives_facts_without_a_profile() -> None:
    df = pd.DataFrame({"segment": ["a", "b"] * 5})
    overview = build_smart_overview(frame=df)
    assert overview.rows == 10
    assert overview.columns == 1
    assert _roles(overview)["segment"] == ROLE_CATEGORICAL


# ---------------------------------------------------------------------------
# Missingness and uniqueness arithmetic
# ---------------------------------------------------------------------------


def test_missing_and_unique_percentages_are_safe_and_rounded() -> None:
    df = pd.DataFrame({"value": [1.0, None, 3.0, 3.0]})
    signal = _signal(_build(df), "value")
    assert signal.non_null == 3
    assert signal.missing_pct == 25.0
    assert signal.distinct == 2
    assert signal.unique_pct == round(2 / 3 * 100, 2)


def test_zero_row_frame_produces_no_division_error_in_percentages() -> None:
    df = pd.DataFrame({"value": pd.Series(dtype="float64")})
    signal = _signal(_build(df), "value")
    assert signal.missing_pct is None
    assert signal.unique_pct is None


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_group_display_is_capped_and_reports_truncation() -> None:
    width = MAX_GROUP_COLUMNS + 5
    df = pd.DataFrame({f"m{i}": [float(i)] * 4 for i in range(width)})
    group = next(g for g in _build(df).groups if g.role == ROLE_MEASURE)
    assert group.total_columns == width
    assert len(group.signals) == MAX_GROUP_COLUMNS
    assert group.truncated is True


def test_content_analysis_column_count_is_bounded() -> None:
    width = MAX_CONTENT_COLUMNS + 10
    df = pd.DataFrame({f"c{i}": ["a", "b"] for i in range(width)})
    overview = _build(df)
    assert overview.columns == width
    assert overview.content_columns_inspected == MAX_CONTENT_COLUMNS


def test_content_analysis_row_count_is_bounded() -> None:
    df = pd.DataFrame({"a": ["x"] * (MAX_CONTENT_ROWS + 100)})
    assert _build(df).content_rows_inspected == MAX_CONTENT_ROWS


def test_wide_dataset_threshold_produces_a_factual_callout() -> None:
    width = WIDE_COLUMN_THRESHOLD + 1
    df = pd.DataFrame({f"m{i}": [float(i)] * 3 for i in range(width)})
    overview = _build(df)
    assert "wide_dataset" in _keys(overview)
    wide = next(c for c in overview.callouts if c.key == "wide_dataset")
    assert wide.evidence == EVIDENCE_FACT


def test_frame_only_distinct_counts_are_bounded_by_column_position() -> None:
    """Beyond the column bound a frame-derived distinct count is *not evaluated*."""
    width = MAX_CONTENT_COLUMNS + 3
    df = pd.DataFrame({f"c{i}": ["a", "b", "a"] for i in range(width)})
    overview = build_smart_overview(frame=df)
    counted = next(g for g in overview.groups if g.role == ROLE_CATEGORICAL)
    uncounted = next(g for g in overview.groups if g.role == ROLE_OTHER)
    assert counted.total_columns == MAX_CONTENT_COLUMNS
    assert uncounted.total_columns == width - MAX_CONTENT_COLUMNS
    assert all(s.distinct == 2 for s in counted.signals)
    assert all(
        s.distinct is None and s.role_evidence == EVIDENCE_UNAVAILABLE for s in uncounted.signals
    )


# ---------------------------------------------------------------------------
# Record strategies
# ---------------------------------------------------------------------------


def test_first_rows_spread_and_most_missing_are_deterministic() -> None:
    frame = pd.DataFrame({"a": list(range(10)), "b": list(range(10))})
    frame.loc[8, "a"] = None
    frame.loc[8, "b"] = None
    frame.loc[5, "a"] = None
    selection = _build(frame).selection
    by_strategy: dict[str, list[int]] = {}
    for record in selection.records:
        by_strategy.setdefault(record.strategy, []).append(record.position)
    assert by_strategy[STRATEGY_FIRST_ROWS] == [0, 1, 2]
    assert by_strategy[STRATEGY_EVEN_SPREAD] == [4, 9]  # 0 already claimed by first_rows
    assert by_strategy[STRATEGY_MOST_MISSING] == [8, 5]


def test_record_selection_is_reproducible_across_calls() -> None:
    frame = pd.DataFrame({"a": list(range(50)), "b": [None] * 50})
    first = [(r.position, r.strategy) for r in _build(frame).selection.records]
    second = [(r.position, r.strategy) for r in _build(frame).selection.records]
    assert first == second


def test_records_are_deduplicated_across_strategies() -> None:
    frame = pd.DataFrame({"a": [1, 2, 3]})
    records = _build(frame).selection.records
    positions = [record.position for record in records]
    assert positions == sorted(set(positions))
    assert len(positions) == len(set(positions))


def test_record_output_is_capped_in_rows_and_columns() -> None:
    width = MAX_RECORD_COLUMNS + 4
    frame = pd.DataFrame({f"c{i}": list(range(40)) for i in range(width)})
    frame.iloc[:20, 0] = None
    selection = _build(frame).selection
    assert len(selection.records) <= MAX_RECORD_ROWS
    assert len(selection.columns) == MAX_RECORD_COLUMNS
    assert selection.total_columns == width
    assert selection.columns_truncated is True


def test_each_strategy_contributes_at_most_its_own_bound() -> None:
    frame = pd.DataFrame({"a": list(range(100)), "b": [None] * 100})
    counts: dict[str, int] = {}
    for record in _build(frame).selection.records:
        counts[record.strategy] = counts.get(record.strategy, 0) + 1
    assert all(count <= MAX_RECORD_ROWS_PER_STRATEGY for count in counts.values())


def test_most_missing_scan_range_is_bounded() -> None:
    rows = MAX_RECORD_SCAN_ROWS + 50
    frame = pd.DataFrame({"a": list(range(rows)), "b": list(range(rows))})
    frame.iloc[rows - 1, 0] = None  # only missing value lies beyond the scan bound
    selection = _build(frame).selection
    assert selection.scanned_rows == MAX_RECORD_SCAN_ROWS
    assert STRATEGY_MOST_MISSING not in selection.strategies


def test_selection_is_unavailable_without_a_frame() -> None:
    profile = {"rows": 10, "cols": 1, "columns": [{"name": "a", "dtype": "int64", "nulls": 0}]}
    selection = build_smart_overview(profile=profile, analysis_mode=ANALYSIS_SAMPLE).selection
    assert selection.available is False
    assert selection.evidence == EVIDENCE_UNAVAILABLE
    assert "no full DataFrame" in selection.reason


# ---------------------------------------------------------------------------
# Callout classification, order, and cap
# ---------------------------------------------------------------------------


def test_duplicate_callout_is_factual_and_only_when_counted() -> None:
    df = pd.DataFrame({"a": [1, 1, 2, 2]})
    assert "duplicate_rows" not in _keys(_build(df))
    with_duplicates = _build(df, duplicate_rows=2)
    callout = next(c for c in with_duplicates.callouts if c.key == "duplicate_rows")
    assert callout.evidence == EVIDENCE_FACT
    assert callout.severity == SEVERITY_ATTENTION


def test_heuristic_callouts_are_labelled_heuristic_not_fact() -> None:
    df = pd.DataFrame(
        {
            "order_id": [f"O{i:03d}" for i in range(10)],
            "signup": [f"2024-01-{i + 1:02d}" for i in range(10)],
        }
    )
    overview = _build(df)
    for key in ("likely_identifiers", "datetime_text"):
        callout = next(c for c in overview.callouts if c.key == key)
        assert callout.evidence == EVIDENCE_HEURISTIC


def test_bounded_sample_numeric_callouts_are_labelled_sample() -> None:
    df = pd.DataFrame({"zeros": [0] * 20, "wild": [float("inf")] * 20})
    overview = _build(df)
    for key in ("zero_heavy_numeric", "non_finite_numeric"):
        callout = next(c for c in overview.callouts if c.key == key)
        assert callout.evidence == EVIDENCE_SAMPLE


def test_high_missingness_and_near_empty_callouts_are_attention_level() -> None:
    df = pd.DataFrame({"a": [None] * 19 + [1.0], "b": [1.0] * 20})
    overview = _build(df)
    assert "high_missingness" in _keys(overview)
    assert "near_empty_columns" in _keys(overview)
    for key in ("high_missingness", "near_empty_columns"):
        callout = next(c for c in overview.callouts if c.key == key)
        assert callout.severity == SEVERITY_ATTENTION


def test_constant_column_callout_excludes_all_null_columns() -> None:
    df = pd.DataFrame({"const": [7] * 10, "empty": [None] * 10})
    overview = _build(df)
    constant = next(c for c in overview.callouts if c.key == "constant_columns")
    assert "`const`" in constant.message
    assert "`empty`" not in constant.message
    assert constant.severity == SEVERITY_NOTE


def test_callouts_are_ranked_attention_first_and_capped() -> None:
    width = WIDE_COLUMN_THRESHOLD + 1
    data: dict[str, list[Any]] = {f"m{i}": [0.0] * 10 for i in range(width)}
    data["mostly_empty"] = [None] * 10
    data["order_id"] = [f"O{i:03d}" for i in range(10)]
    data["signup"] = [f"2024-01-{i + 1:02d}" for i in range(10)]
    overview = _build(pd.DataFrame(data), duplicate_rows=4)
    ranks = [0 if c.severity == SEVERITY_ATTENTION else 1 for c in overview.callouts]
    assert ranks == sorted(ranks)
    assert len(overview.callouts) == MAX_CALLOUTS


def test_callout_order_is_reproducible() -> None:
    df = pd.DataFrame(
        {
            "order_id": [f"O{i:03d}" for i in range(10)],
            "empty": [None] * 10,
            "zeros": [0] * 10,
        }
    )
    assert _keys(_build(df, duplicate_rows=1)) == _keys(_build(df, duplicate_rows=1))


# ---------------------------------------------------------------------------
# Large-mode honesty
# ---------------------------------------------------------------------------


def test_sample_mode_downgrades_every_exact_fact() -> None:
    df = pd.DataFrame({"amount": [1.0, 2.0, 3.0, 4.0], "when": pd.to_datetime(["2024-01-01"] * 4)})
    overview = _build(df, analysis_mode=ANALYSIS_SAMPLE)
    assert overview.sample_derived is True
    assert overview.shape_evidence == EVIDENCE_SAMPLE
    assert all(s.role_evidence != EVIDENCE_FACT for s in overview.displayed_signals)


def test_full_mode_keeps_exact_facts_labelled_as_facts() -> None:
    df = pd.DataFrame({"amount": [1.0, 2.0, 3.0, 4.0]})
    overview = _build(df, analysis_mode=ANALYSIS_FULL)
    assert overview.sample_derived is False
    assert overview.shape_evidence == EVIDENCE_FACT


def test_unknown_analysis_mode_falls_back_to_full() -> None:
    df = pd.DataFrame({"amount": [1.0, 2.0]})
    assert _build(df, analysis_mode="nonsense").analysis_mode == ANALYSIS_FULL


def test_every_evidence_class_has_operator_facing_wording() -> None:
    for evidence in (EVIDENCE_FACT, EVIDENCE_SAMPLE, EVIDENCE_HEURISTIC, EVIDENCE_UNAVAILABLE):
        assert EVIDENCE_LABELS[evidence]


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_preview_identity_line_joins_only_populated_parts() -> None:
    identity = PreviewIdentity(
        status="Managed version",
        label="data.csv",
        short_version_id="v-1a2b3c4d",
        mode_label="full analysis mode",
    )
    assert identity.line == "Managed version v-1a2b3c4d · data.csv · full analysis mode"
    assert PreviewIdentity(status="Legacy dataset", label="x").line == "Legacy dataset · x"


def test_identity_is_carried_through_to_the_overview() -> None:
    identity = PreviewIdentity(status="Managed version", label="orders.csv")
    overview = build_smart_overview(identity=identity)
    assert overview.identity is identity


# ---------------------------------------------------------------------------
# Purity guarantees
# ---------------------------------------------------------------------------


def test_builder_never_mutates_the_input_frame() -> None:
    df = pd.DataFrame(
        {
            "order_id": [f"O{i:03d}" for i in range(10)],
            "signup": [f"2024-01-{i + 1:02d}" for i in range(10)],
            "amount": [float(i) for i in range(10)],
            "empty": [None] * 10,
        }
    )
    df.loc[4, "amount"] = None
    before = df.copy(deep=True)
    _build(df, duplicate_rows=1)
    pd.testing.assert_frame_equal(df, before)
    assert list(df.columns) == list(before.columns)
    assert [str(d) for d in df.dtypes] == [str(d) for d in before.dtypes]


def test_builder_never_mutates_the_input_profile() -> None:
    df = pd.DataFrame({"a": [1, 2, 3]})
    profile = _profile_for(df)
    snapshot = _profile_for(df)
    build_smart_overview(profile=profile, frame=df)
    assert profile == snapshot


def _module_imports() -> set[str]:
    tree = ast.parse(inspect.getsource(sdo))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.add(node.module)
    return names


def test_service_imports_no_streamlit_filesystem_or_random_module() -> None:
    roots = {name.split(".")[0] for name in _module_imports()}
    forbidden = {"streamlit", "os", "pathlib", "io", "random", "shutil", "requests", "urllib"}
    assert roots.isdisjoint(forbidden), f"forbidden import root: {roots & forbidden}"


def test_service_source_never_opens_a_file_or_reads_session_state() -> None:
    source = inspect.getsource(sdo)
    for token in ("open(", "read_csv", "session_state", "st.", "np.random", "sample("):
        assert token not in source, f"forbidden construct in pure service: {token!r}"


def test_service_stays_inside_the_ui_service_layer() -> None:
    assert sdo.__name__ == "data_quality_toolkit.adapters.ui.services.smart_data_overview"
    package_names = {name for name in _module_imports() if name.startswith("data_quality_toolkit")}
    assert package_names == set(), f"pure service must stay dependency-free: {package_names}"
