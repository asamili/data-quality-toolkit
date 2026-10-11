"""Pure tests for the rules-based EDA Smart Guide."""

from __future__ import annotations

import pandas as pd

from data_quality_toolkit.adapters.ui.eda import (
    GUIDE_MAX_RECOMMENDATIONS,
    MAX_CORRELATION_COLUMNS,
    MAX_PLOT_ROWS,
)
from data_quality_toolkit.adapters.ui.eda_guide import (
    EDA_TARGET_TABS,
    recommend_eda_actions,
    recommend_visual_explorations,
)


def _matching_titles(df: pd.DataFrame, text: str) -> list[str]:
    return [
        recommendation.title
        for recommendation in recommend_eda_actions(df)
        if text.lower() in recommendation.title.lower()
        or text.lower() in recommendation.message.lower()
        or text.lower() in recommendation.target_tab.lower()
    ]


def test_empty_dataframe_returns_safe_output() -> None:
    assert recommend_eda_actions(pd.DataFrame()) == []
    assert recommend_eda_actions(pd.DataFrame(index=[0, 1, 2])) == []


def test_high_missingness_produces_warning() -> None:
    df = pd.DataFrame({"mostly_missing": [None, None, None, 1.0], "ok": [1, 2, 3, 4]})

    recommendations = recommend_eda_actions(df)

    assert any(
        recommendation.severity == "warning"
        and recommendation.columns == ("mostly_missing",)
        and "missing" in recommendation.title.lower()
        for recommendation in recommendations
    )


def test_high_cardinality_categorical_produces_recommendation() -> None:
    df = pd.DataFrame({"category": [f"cat-{i}" for i in range(25)]})

    assert _matching_titles(df, "high-cardinality")


def test_strong_numeric_correlation_produces_relationships_recommendation() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [2.0, 4.0, 6.0, 8.0, 10.0]})

    recommendations = recommend_eda_actions(df)

    assert any(
        recommendation.target_tab == "Relationships"
        and recommendation.columns == ("a", "b")
        and "correlation" in recommendation.message.lower()
        for recommendation in recommendations
    )


def test_skewed_numeric_column_produces_recommendation() -> None:
    df = pd.DataFrame({"amount": [1.0] * 30 + [1000.0]})

    recommendations = recommend_eda_actions(df)

    assert any(
        recommendation.columns == ("amount",)
        and "skew" in recommendation.message.lower()
        and recommendation.target_tab == "Columns"
        for recommendation in recommendations
    )


def test_datetime_like_column_produces_time_recommendation() -> None:
    df = pd.DataFrame({"ts": ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]})

    recommendations = recommend_eda_actions(df)

    assert any(recommendation.target_tab == "Time" for recommendation in recommendations)


def test_dominant_categorical_value_produces_imbalance_recommendation() -> None:
    df = pd.DataFrame({"segment": ["retail"] * 19 + ["enterprise"]})

    recommendations = recommend_eda_actions(df)

    assert any(
        recommendation.columns == ("segment",) and "imbalance" in recommendation.title.lower()
        for recommendation in recommendations
    )


def test_row_count_above_plot_cap_produces_sampling_recommendation() -> None:
    df = pd.DataFrame({"n": range(MAX_PLOT_ROWS + 1)})

    recommendations = recommend_eda_actions(df)

    assert any("sampling" in recommendation.title.lower() for recommendation in recommendations)


def test_numeric_column_count_above_correlation_cap_produces_recommendation() -> None:
    df = pd.DataFrame({f"n{i}": [float(i)] for i in range(MAX_CORRELATION_COLUMNS + 1)})

    recommendations = recommend_eda_actions(df)

    assert any(
        recommendation.target_tab == "Advanced"
        and "correlation heatmap" in recommendation.title.lower()
        for recommendation in recommendations
    )


def test_max_recommendations_cap_is_honored() -> None:
    df = pd.DataFrame({f"missing_{i}": [None, None, None, 1.0] for i in range(5)})

    recommendations = recommend_eda_actions(df, max_recommendations=3)

    assert len(recommendations) == 3


def test_input_dataframe_is_not_mutated() -> None:
    df = pd.DataFrame(
        {
            "missing": [None, 1.0, 2.0, 3.0],
            "category": ["a", "b", "c", "d"],
            "numeric": [1.0, 2.0, 3.0, 4.0],
        }
    )
    original = df.copy(deep=True)

    recommend_eda_actions(df)

    pd.testing.assert_frame_equal(df, original)


# ── type-aware visual discovery guide (P2) ───────────────────────────────────


def _visual_text(df: pd.DataFrame) -> str:
    return " ".join(
        f"{item.question} {item.visual} {item.reason} {item.caveat} {item.target_tab}"
        for item in recommend_visual_explorations(df)
    )


def test_visual_guide_is_empty_for_an_empty_frame() -> None:
    assert recommend_visual_explorations(pd.DataFrame()) == []


def test_visual_guide_is_deterministic_across_repeated_calls() -> None:
    df = pd.DataFrame(
        {
            "amount": [float(i) for i in range(20)],
            "score": [float(i * 2) for i in range(20)],
            "segment": ["a" if i % 2 else "b" for i in range(20)],
        }
    )

    first = recommend_visual_explorations(df)
    second = recommend_visual_explorations(df)

    assert first == second
    assert [item.target_tab for item in first] == [item.target_tab for item in second]


def test_visual_guide_honors_the_recommendation_cap() -> None:
    df = pd.DataFrame(
        {
            "amount": [float(i) for i in range(30)],
            "score": [float((i * 5) % 11) for i in range(30)],
            "partial": [None if i % 3 else float(i) for i in range(30)],
            "other_partial": [None if i % 3 else float(i) for i in range(30)],
            "segment": ["a" if i % 2 else "b" for i in range(30)],
            "region": ["p" if i % 3 else "q" for i in range(30)],
            "ts": pd.date_range("2025-01-01", periods=30, freq="D").astype(str),
        }
    )

    assert len(recommend_visual_explorations(df)) <= GUIDE_MAX_RECOMMENDATIONS
    assert len(recommend_visual_explorations(df, max_recommendations=3)) == 3
    assert recommend_visual_explorations(df, max_recommendations=0) == []
    # A caller cannot raise the cap above the declared ceiling.
    assert len(recommend_visual_explorations(df, max_recommendations=99)) <= (
        GUIDE_MAX_RECOMMENDATIONS
    )


def test_visual_guide_covers_numeric_univariate_shape() -> None:
    df = pd.DataFrame({"amount": [float(i) for i in range(20)]})

    text = _visual_text(df)

    assert "Histogram" in text
    assert "ECDF" in text
    assert "box plot" in text
    assert "Q-Q" in text


def test_visual_guide_suggests_log_scale_for_skewed_positive_numeric() -> None:
    df = pd.DataFrame({"amount": [1.0] * 30 + [5000.0]})

    text = _visual_text(df)

    assert "log-scale" in text.lower()


def test_visual_guide_covers_categorical_concentration() -> None:
    df = pd.DataFrame({"segment": ["a"] * 20 + ["b"] * 10 + ["c"] * 5})

    text = _visual_text(df)

    assert "Top-N" in text
    assert "Pareto" in text


def test_visual_guide_covers_missingness_structure() -> None:
    df = pd.DataFrame(
        {
            "a": [None if i % 2 else 1.0 for i in range(20)],
            "b": [None if i % 3 else 2.0 for i in range(20)],
        }
    )

    text = _visual_text(df)

    assert "missingness pattern" in text.lower()
    assert "association" in text.lower()
    assert "MCAR, MAR or MNAR" in text


def test_visual_guide_covers_numeric_numeric_pairs() -> None:
    df = pd.DataFrame(
        {"amount": [float(i) for i in range(20)], "score": [float(i % 7) for i in range(20)]}
    )

    text = _visual_text(df)

    assert "Scatter" in text
    assert "density" in text
    assert "correlation" in text.lower()


def test_visual_guide_covers_numeric_categorical_pairs() -> None:
    df = pd.DataFrame(
        {
            "amount": [float(i) for i in range(20)],
            "segment": ["a" if i % 2 else "b" for i in range(20)],
        }
    )

    text = _visual_text(df)

    assert "distribution by category" in text.lower()


def test_visual_guide_covers_categorical_categorical_pairs() -> None:
    df = pd.DataFrame(
        {
            "segment": ["a" if i % 2 else "b" for i in range(20)],
            "region": ["p" if i % 3 else "q" for i in range(20)],
        }
    )

    text = _visual_text(df)

    assert "Crosstab" in text
    assert "stacked" in text
    assert "association" in text.lower()


def test_visual_guide_covers_datetime_numeric_pairs() -> None:
    df = pd.DataFrame(
        {
            "ts": pd.date_range("2025-01-01", periods=20, freq="D").astype(str),
            "amount": [float(i) for i in range(20)],
        }
    )

    text = _visual_text(df)

    assert "trend" in text.lower()
    assert "aggregation" in text.lower()


def test_visual_guide_covers_datetime_categorical_pairs() -> None:
    df = pd.DataFrame(
        {
            "ts": pd.date_range("2025-01-01", periods=20, freq="D").astype(str),
            "segment": ["a" if i % 2 else "b" for i in range(20)],
        }
    )

    text = _visual_text(df)

    assert "over time" in text.lower() or "counts over time" in text.lower()


def test_visual_guide_warns_about_identifier_like_columns_instead_of_charting_them() -> None:
    df = pd.DataFrame({"row_key": [f"k-{i}" for i in range(60)]})

    recommendations = recommend_visual_explorations(df)

    flagged = [item for item in recommendations if not item.available]
    assert flagged, "identifier-like columns must be surfaced as not recommended"
    assert flagged[0].columns == ("row_key",)
    assert "identifier-like" in flagged[0].caveat
    # The same column is never proposed for a category chart.
    assert all("Pareto" not in item.visual for item in recommendations)


def test_visual_guide_targets_are_real_eda_tabs() -> None:
    df = pd.DataFrame(
        {
            "amount": [float(i) for i in range(20)],
            "partial": [None if i % 3 else float(i) for i in range(20)],
            "segment": ["a" if i % 2 else "b" for i in range(20)],
            "ts": pd.date_range("2025-01-01", periods=20, freq="D").astype(str),
        }
    )

    for item in recommend_visual_explorations(df):
        assert item.target_tab in EDA_TARGET_TABS


def test_visual_guide_always_carries_a_question_and_a_caveat() -> None:
    df = pd.DataFrame(
        {
            "amount": [float(i) for i in range(20)],
            "segment": ["a" if i % 2 else "b" for i in range(20)],
        }
    )

    for item in recommend_visual_explorations(df):
        assert item.question.strip()
        assert item.visual.strip()
        assert item.reason.strip()
        assert item.caveat.strip()


def test_visual_guide_never_uses_formal_test_or_significance_wording() -> None:
    df = pd.DataFrame(
        {
            "amount": [float(i) for i in range(30)],
            "score": [float((i * 5) % 11) for i in range(30)],
            "partial": [None if i % 3 else float(i) for i in range(30)],
            "segment": ["a" if i % 2 else "b" for i in range(30)],
            "region": ["p" if i % 3 else "q" for i in range(30)],
            "ts": pd.date_range("2025-01-01", periods=30, freq="D").astype(str),
        }
    )

    text = _visual_text(df).lower()

    for token in (
        "p-value",
        "p value",
        "significant",
        "significance level",
        "null hypothesis",
        "reject",
        "confidence interval",
        "t-test",
        "chi-square",
    ):
        assert token not in text, f"visual guide must not use inferential wording: {token}"


def test_visual_guide_does_not_mutate_the_input_frame() -> None:
    df = pd.DataFrame(
        {
            "amount": [1.0, 2.0, None, 4.0],
            "segment": ["a", "b", "a", None],
        }
    )
    original = df.copy(deep=True)

    recommend_visual_explorations(df)

    pd.testing.assert_frame_equal(df, original)


def test_visual_guide_survives_messy_columns() -> None:
    df = pd.DataFrame(
        {
            "numeric": [1.0, float("inf"), float("-inf"), None],
            "constant": [5.0, 5.0, 5.0, 5.0],
            "flag": [True, True, None, False],
            "messy_category": [{"a": 1}, ["x"], None, {"b": 2}],
            "maybe_date": ["not-a-date", None, "2025-01-01", object()],
        }
    )

    assert isinstance(recommend_visual_explorations(df), list)


def test_messy_data_with_missing_inf_constant_and_boolean_values_does_not_raise() -> None:
    df = pd.DataFrame(
        {
            "numeric": [1.0, float("inf"), float("-inf"), None],
            "constant": [5.0, 5.0, 5.0, 5.0],
            "flag": [True, True, None, False],
            "messy_category": [{"a": 1}, ["x"], None, {"b": 2}],
            "maybe_date": ["not-a-date", None, "2025-01-01", object()],
        }
    )

    recommendations = recommend_eda_actions(df)

    assert isinstance(recommendations, list)
