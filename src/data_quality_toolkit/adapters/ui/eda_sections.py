"""Section renderers for the EDA Explorer page."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

import pandas as pd

from data_quality_toolkit.adapters.ui.components.downloads import csv_download_button
from data_quality_toolkit.adapters.ui.components.storylens import render_storylens_card
from data_quality_toolkit.adapters.ui.components.workspace_save_ui import render_analysis_csv_save
from data_quality_toolkit.adapters.ui.eda import (
    CATEGORICAL_ASSOC_MAX_COLUMNS,
    CATEGORICAL_ASSOC_MAX_LEVELS,
    CATEGORICAL_ASSOC_MAX_ROWS,
    CORRELATION_METHODS,
    DATETIME_PARSE_THRESHOLD,
    DEFAULT_HISTOGRAM_BINS,
    GUIDE_MAX_RECOMMENDATIONS,
    MAX_CORRELATION_COLUMNS,
    MAX_GROUP_CATEGORIES,
    MAX_HISTOGRAM_BINS,
    MAX_OUTLIER_COLUMNS,
    MAX_SUMMARY_COLUMNS,
    MAX_TOP_CATEGORIES,
    MIN_HISTOGRAM_BINS,
    NUMERIC_CORRELATION_MAX_COLUMNS,
    PARETO_MAX_CATEGORIES,
    PARETO_MIN_CATEGORY_COUNT,
    QQ_MAX_POINTS,
    QQ_MIN_OBSERVATIONS,
    _aggregate_iqr_outlier_summary,
    _bounded_density_heatmap_data,
    _bounded_scatter_data,
    _boxplot_data,
    _categorical_association_data,
    _categorical_crosstab_data,
    _categorical_crosstab_heatmap_data,
    _categorical_top_frequency_data,
    _correlation_heatmap_data,
    _dataset_profile,
    _datetime_candidate_columns,
    _datetime_categorical_counts_data,
    _datetime_numeric_aggregation_data,
    _datetime_trend_data,
    _density_curve_data,
    _dtype_distribution,
    _duplicate_row_summary,
    _iqr_outlier_summary,
    _missingness_association_data,
    _missingness_bar_data,
    _missingness_pattern_data,
    _missingness_summary,
    _numeric_by_category_summary_data,
    _numeric_correlation_columns,
    _numeric_ecdf_data,
    _numeric_histogram_data,
    _outlier_bar_data,
    _pareto_category_data,
    _qq_normal_data,
    _skew_kurtosis_summary,
)
from data_quality_toolkit.adapters.ui.eda_guide import (
    EdaRecommendation,
    VisualRecommendation,
    recommend_eda_actions,
    recommend_visual_explorations,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    BIV_COL1,
    BIV_COL1_NEXT_BTN,
    BIV_COL1_PREV_BTN,
    BIV_COL2,
    BIV_COL2_NEXT_BTN,
    BIV_COL2_PREV_BTN,
    BIV_CROSSTAB_HEATMAP,
    BIV_CROSSTAB_NORMALIZE,
    BIV_DENSITY_HEATMAP,
    BIV_DT_CAT_TOP_N,
    BIV_DT_GRANULARITY,
    BIV_DT_NUM_AGG,
    BIV_SCATTER_CLIP_AXES,
    BIV_SCATTER_LOG_SCALE,
    BIV_SCATTER_TREND_LINE,
    BIV_SWAP_BTN,
    EDA_CAT_OTHER_BUCKET,
    EDA_CORR_METHOD,
    EDA_DT_GRANULARITY,
    EDA_HIST_AUTO_BINS,
)
from data_quality_toolkit.application.explanation import (
    Explanation,
    explain_missing_value_issue,
    explain_quality_score,
)

# Human label -> pandas corr method for the EDA correlation selector.
_CORR_METHOD_LABELS = {method.title(): method for method in CORRELATION_METHODS}

_SAVE_MISSINGNESS_BTN = "eda_save_missingness"
_SAVE_DISTRIBUTION_BTN = "eda_save_distribution"
_SAVE_CATEGORIES_BTN = "eda_save_categories"
_SAVE_SKEW_KURTOSIS_BTN = "eda_save_skew_kurtosis"
_SAVE_CORRELATION_BTN = "eda_save_correlation"
_SAVE_OUTLIERS_BTN = "eda_save_outliers"
_SAVE_NUMERIC_BY_CATEGORY_BTN = "eda_save_numeric_by_category"
_SAVE_CROSSTAB_BTN = "eda_save_crosstab"
_SAVE_DENSITY_HEATMAP_BTN = "eda_save_density_heatmap"
_SAVE_TIME_AGGREGATION_BTN = "eda_save_time_aggregation"
_SAVE_TIME_CATEGORIES_BTN = "eda_save_time_categories"
_SAVE_PARETO_BTN = "eda_save_pareto"
_SAVE_MISSING_ASSOC_BTN = "eda_save_missingness_association"
_SAVE_CORRELATION_PAIRS_BTN = "eda_save_correlation_pairs"
_SAVE_CATEGORICAL_ASSOC_BTN = "eda_save_categorical_association"

# Widget keys for the P2 visual-discovery controls. These are local EDA widget
# identities (same convention as the save-button keys above); they are not
# shared session-state contract keys.
_EDA_HIST_LOG_SCALE = "eda_hist_log_scale"
_EDA_SHOW_QQ = "eda_show_qq"
_EDA_SHOW_PARETO = "eda_show_pareto"
_EDA_SHOW_MISSING_STRUCTURE = "eda_show_missing_structure"
_EDA_CORR_COLUMNS = "eda_corr_columns"
_EDA_SHOW_CORR_PAIRS = "eda_show_corr_pairs"
_EDA_SHOW_CAT_ASSOC = "eda_show_cat_assoc"
_EDA_CAT_ASSOC_COLUMNS = "eda_cat_assoc_columns"
_BIV_CROSSTAB_STACKED = "eda_biv_crosstab_stacked"

# Fixed exploratory-honesty captions. Each states what an exploratory visual can
# and cannot support, so a chart is never read as a confirmed statistical result.
_QQ_CAVEAT = (
    "Q-Q is a visual diagnostic: points near the reference line suggest a "
    "normal-like shape. It is not a normality test and reports no p-value — "
    "run formal tests in Statistics Lab."
)
_PARETO_CAVEAT = (
    "Concentration describes where rows pile up. It does not mean the leading "
    "categories are the important or causal ones."
)
_MISSINGNESS_PATTERN_CAVEAT = (
    "Row positions are sequential display positions only. No source row "
    "identifiers, index labels, or cell values are shown."
)
_MISSINGNESS_MECHANISM_CAVEAT = (
    "Columns becoming missing together may indicate a shared process, but this "
    "does not determine whether data are MCAR, MAR or MNAR."
)
_CORRELATION_PAIRS_CAVEAT = (
    "Ranked by absolute strength on the analyzed columns. Correlation does not "
    "establish causation and carries no significance claim."
)
_CATEGORICAL_ASSOC_CAVEAT = (
    "Association strength describes how categories vary together in the "
    "analyzed data; it does not prove causation or statistical significance."
)
_NUM_NUM_CAVEAT = (
    "A visible pattern between two numeric columns describes co-movement in "
    "these rows only; it does not establish causation."
)
_NUM_CAT_CAVEAT = (
    "Differences between groups here are descriptive. Comparing groups formally "
    "belongs in Statistics Lab."
)
_TIME_PAIR_CAVEAT = (
    "A movement over time reflects the rows present in each bucket; uneven "
    "coverage can create an apparent trend."
)
_ANALYSIS_SAVE_CAPTION = (
    "Downloads stay in your browser. Optionally save this EDA output under your "
    "Workspace Root / analysis; existing files are not overwritten."
)

# Always-visible per-tab intro captions. Each states what the tab helps answer
# and names the analyses/plots/outputs already available on it, so operators can
# discover capabilities without clicking through every tab. These describe only
# implemented behavior and must stay path-safe (no absolute paths or internals).
_OVERVIEW_TAB_INTRO = (
    "Dataset health at a glance — quality score, guided next steps (Smart Guide) "
    "with suggested visuals, missingness and its structural pattern, duplicate "
    "rows, and column data types."
)
_COLUMNS_TAB_INTRO = (
    "Explore one column at a time — numeric distributions (histogram with an "
    "optional log scale, density, boxplot, ECDF, Q-Q diagnostic, IQR outliers) "
    "and categorical top values with an optional Other bucket and Pareto view."
)
_RELATIONSHIPS_TAB_INTRO = (
    "Compare any two columns — the view adapts to the pair: scatter and 2D density "
    "(numeric×numeric), box-by-category (numeric×categorical), crosstab, heatmap and "
    "100% stacked comparison (categorical×categorical), and time series (datetime pairs)."
)
_TIME_TAB_INTRO = (
    "Trend a metric over a datetime column by day, week, or month. For a datetime "
    "column paired with another column, use the Relationships tab."
)
_ADVANCED_TAB_INTRO = (
    "Cross-column summaries — distribution shape (skewness & kurtosis), a "
    "correlation matrix with ranked pairs over a chosen numeric subset, a "
    "categorical association matrix, and an outlier overview."
)


def _render_csv_actions(
    st: Any,
    *,
    download_label: str,
    dataframe: pd.DataFrame,
    file_name: str,
    button_label: str,
    key: str,
    artifact: str,
    dataset_name: str | None = None,
) -> None:
    csv_download_button(st, download_label, dataframe, file_name)
    render_analysis_csv_save(
        st,
        button_label=button_label,
        key=key,
        artifact=artifact,
        dataframe=dataframe,
        dataset_name=dataset_name,
        caption=_ANALYSIS_SAVE_CAPTION,
    )


def _eda_storylens(
    result: dict[str, Any] | None, profile: Mapping[str, Any] | None
) -> list[Explanation]:
    """Build bounded deterministic StoryLens cards from EDA assessment facts.

    Returns at most 2 cards (quality score + first missing-value issue).
    Returns [] on any unexpected error — never raises, never fabricates.
    """
    try:
        assessment = (result or {}).get("assessment") or {}
        score_raw = assessment.get("score")
        if score_raw is None or profile is None:
            return []
        score = float(score_raw)
        rows = int(profile["rows"])
        cols = int(profile["cols"])
        issues: list[dict[str, Any]] = list(assessment.get("issues") or [])
        cards: list[Explanation] = [
            explain_quality_score(
                score=score,
                rows=rows,
                columns=cols,
                issues_total=len(issues),
            )
        ]
        for issue in issues:
            if issue.get("type") == "missing":
                column = issue.get("column")
                pct = issue.get("pct")
                if column and isinstance(pct, int | float) and not isinstance(pct, bool):
                    cards.append(
                        explain_missing_value_issue(
                            column=str(column),
                            null_pct=float(pct),
                            severity_label=str(issue.get("severity", "medium")),
                        )
                    )
                    break
        return cards
    except Exception:
        return []


def _render_dataset_profile(
    st: Any, df: pd.DataFrame, profile: Mapping[str, Any] | None = None
) -> None:
    st.subheader("Dataset profile")
    facts = _dataset_profile(df, profile)
    cards = st.columns(4)
    cards[0].metric("Rows", f"{facts['rows']:,}")
    cards[1].metric("Columns", f"{facts['columns']:,}")
    cards[2].metric("Missing cells", f"{facts['missing_cells']:,}")
    cards[3].metric("Memory", f"{facts['memory_mb']:.2f} MB")


def _render_missingness(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    st.subheader("Missingness")
    chart = _missingness_bar_data(df)
    if chart["status"] != "ok":
        st.info("No columns to summarize.")
        return
    chart_df = chart["data"]
    st.bar_chart(chart_df.set_index("column")[["missing_pct"]])
    with st.expander("Missingness details"):
        detail = _missingness_summary(df)
        st.dataframe(detail, hide_index=True)
        _render_csv_actions(
            st,
            download_label="Download missingness data (CSV)",
            dataframe=detail,
            file_name="eda_missingness.csv",
            button_label="Save missingness data to workspace",
            key=_SAVE_MISSINGNESS_BTN,
            artifact="eda_missingness",
            dataset_name=dataset_name,
        )
    if df.shape[1] > MAX_SUMMARY_COLUMNS:
        st.caption(f"Showing the first {MAX_SUMMARY_COLUMNS} columns to keep the view responsive.")


def _render_missingness_pattern(st: Any, df: pd.DataFrame) -> bool:
    """Render the anonymous present/missing pattern matrix. Returns True when drawn."""
    pattern = _missingness_pattern_data(df)
    if pattern["status"] != "ok":
        st.info("No missing values to map — every column in this dataset is complete.")
        return False
    st.caption(
        f"Missingness pattern — {pattern['columns_displayed']} column(s) with missing "
        f"values across {pattern['plot_rows']:,} row positions. "
        f"{_MISSINGNESS_PATTERN_CAVEAT}"
    )
    st.vega_lite_chart(
        pattern["data"],
        {
            "mark": "rect",
            "encoding": {
                "x": {"field": "row_position", "type": "ordinal", "title": "Row position"},
                "y": {"field": "column", "type": "nominal", "title": None},
                "color": {
                    "field": "missing",
                    "type": "quantitative",
                    "title": "Missing",
                    "scale": {"domain": [0, 1], "scheme": "greys"},
                },
                "tooltip": [
                    {"field": "column", "type": "nominal"},
                    {"field": "missing", "type": "quantitative", "title": "Missing (1 = yes)"},
                ],
            },
        },
        use_container_width=True,
    )
    if pattern["row_sampled"] or pattern["column_truncated"]:
        st.caption(
            f"Bounded view: {pattern['plot_rows']:,} of {pattern['source_rows']:,} rows "
            f"(evenly spaced, deterministic) and {pattern['columns_displayed']} of "
            f"{pattern['columns_with_missing']} columns with missing values."
        )
    return True


def _render_missingness_association(st: Any, df: pd.DataFrame, *, dataset_name: str | None) -> None:
    """Render the signed missingness-association heatmap and its ranked pairs."""
    assoc = _missingness_association_data(df)
    if assoc["status"] != "ok":
        st.info(
            "Missingness association needs at least two columns whose missingness varies "
            "across rows."
        )
        return
    st.caption("Missingness association — how often columns are missing on the same rows.")
    st.vega_lite_chart(
        assoc["data"],
        {
            "mark": "rect",
            "encoding": {
                "x": {"field": "x", "type": "nominal", "title": None},
                "y": {"field": "y", "type": "nominal", "title": None},
                "color": {
                    "field": "association",
                    "type": "quantitative",
                    "scale": {"domain": [-1, 1], "scheme": "redblue"},
                },
                "tooltip": [
                    {"field": "x", "type": "nominal"},
                    {"field": "y", "type": "nominal"},
                    {"field": "association", "type": "quantitative"},
                ],
            },
        },
        use_container_width=True,
    )
    pairs = assoc["pairs"]
    if not pairs.empty:
        with st.expander("Strongest missingness pairs"):
            st.dataframe(pairs, hide_index=True)
            _render_csv_actions(
                st,
                download_label="Download missingness association (CSV)",
                dataframe=pairs,
                file_name="eda_missingness_association.csv",
                button_label="Save missingness association to workspace",
                key=_SAVE_MISSING_ASSOC_BTN,
                artifact="eda_missingness_association",
                dataset_name=dataset_name,
            )
    if assoc["row_sampled"]:
        st.caption(
            f"Sample-derived: computed on {assoc['rows_used']:,} of "
            f"{assoc['source_rows']:,} rows (evenly spaced, deterministic)."
        )
    st.caption(_MISSINGNESS_MECHANISM_CAVEAT)


def _render_structural_missingness(
    st: Any, df: pd.DataFrame, *, dataset_name: str | None = None
) -> None:
    """Render the opt-in structural-missingness block (pattern map + association).

    Kept behind an explicit control so the pattern and association matrices are
    only computed when an operator asks for them.
    """
    st.subheader("Missingness structure")
    show = st.checkbox(
        "Show missingness structure (pattern map and association)",
        key=_EDA_SHOW_MISSING_STRUCTURE,
    )
    if not show:
        st.caption("Optional: map where missing values fall and which columns go missing together.")
        return
    if not _render_missingness_pattern(st, df):
        return
    _render_missingness_association(st, df, dataset_name=dataset_name)


def _render_duplicate_rows(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Duplicate rows")
    summary = _duplicate_row_summary(df)
    cards = st.columns(3)
    cards[0].metric("Duplicate rows", f"{summary['duplicate_rows']:,}")
    cards[1].metric("Duplicate rate", f"{summary['duplicate_pct']:.2f}%")
    cards[2].metric("Unique rows", f"{summary['unique_rows']:,}")
    st.caption("Counts fully duplicated rows; source records are not displayed.")


def _render_dtype_distribution(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Data types")
    summary = _dtype_distribution(df)
    if summary.empty:
        st.info("No data types to summarize.")
        return
    st.dataframe(summary, hide_index=True)


def _render_smart_guide(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Smart Guide")
    st.caption("Rules-based checks from this dataset. No AI or external model is used.")
    recommendations = recommend_eda_actions(df, max_recommendations=GUIDE_MAX_RECOMMENDATIONS)
    if not recommendations:
        st.info("No major EDA warnings found from the current rule checks.")
    for recommendation in recommendations:
        body = _format_smart_guide_recommendation(recommendation)
        if recommendation.severity == "warning":
            st.warning(body)
        else:
            st.info(body)
        if recommendation.reason:
            st.caption(f"Reason: {recommendation.reason}")
    _render_visual_guide(st, df)


def _format_smart_guide_recommendation(recommendation: EdaRecommendation) -> str:
    lines = [
        f"**{recommendation.title}**",
        recommendation.message,
        f"Target tab: {recommendation.target_tab}",
    ]
    if recommendation.columns:
        lines.append(f"Columns: {', '.join(recommendation.columns)}")
    return "\n\n".join(lines)


def _render_visual_guide(st: Any, df: pd.DataFrame) -> None:
    """Render deterministic, type-aware suggestions for what to look at next.

    Suggestions point at existing EDA sections and always carry a caveat, so a
    suggested chart is read as a question to explore rather than a conclusion.
    """
    suggestions = recommend_visual_explorations(df, max_recommendations=GUIDE_MAX_RECOMMENDATIONS)
    if not suggestions:
        return
    with st.expander(f"Suggested visuals ({len(suggestions)})"):
        st.caption(
            "Deterministic suggestions based on the column types and bounded facts "
            "in this dataset. Exploratory only — no statistical test is selected or run."
        )
        for suggestion in suggestions:
            st.markdown(_format_visual_recommendation(suggestion))
            st.caption(f"Why: {suggestion.reason} — {suggestion.caveat}")


def _format_visual_recommendation(suggestion: VisualRecommendation) -> str:
    status = "Available" if suggestion.available else "Not recommended"
    lines = [
        f"**{suggestion.question}**",
        f"Try: {suggestion.visual}",
        f"Where: {suggestion.target_tab} tab ({status})",
    ]
    if suggestion.columns:
        lines.append(f"Columns: {', '.join(suggestion.columns)}")
    return "\n\n".join(lines)


def _render_univariate_numeric(
    st: Any,
    df: pd.DataFrame,
    numeric_columns: list[Any],
    *,
    dataset_name: str | None = None,
) -> None:
    """Render the numeric distribution block (histogram, density, boxplot, outliers)."""
    st.subheader("Numeric distributions")
    if not numeric_columns:
        st.info("No numeric columns to explore.")
        return
    col_name = st.selectbox("Select numeric column", numeric_columns)
    auto_bins = st.checkbox("Auto bins (Freedman–Diaconis)", value=True, key=EDA_HIST_AUTO_BINS)
    bins: int | None = None
    if not auto_bins:
        bins = int(
            st.number_input(
                "Histogram bins",
                min_value=MIN_HISTOGRAM_BINS,
                max_value=MAX_HISTOGRAM_BINS,
                value=DEFAULT_HISTOGRAM_BINS,
                step=1,
            )
        )
    log_scale = st.checkbox(
        "Log-scale the histogram value axis (positive values only)", key=_EDA_HIST_LOG_SCALE
    )
    hist = _numeric_histogram_data(df, col_name, bins=bins)
    if hist["status"] == "ok":
        effective_bins = int(hist.get("effective_bins", DEFAULT_HISTOGRAM_BINS))
        st.caption(f"Distribution ({effective_bins} bins)")
        if not (log_scale and _render_log_histogram(st, hist["data"], col_name)):
            st.bar_chart(hist["data"].set_index("bin")[["count"]])
        _render_csv_actions(
            st,
            download_label="Download distribution data (CSV)",
            dataframe=hist["data"],
            file_name="eda_distribution.csv",
            button_label="Save distribution data to workspace",
            key=_SAVE_DISTRIBUTION_BTN,
            artifact="eda_distribution",
            dataset_name=dataset_name,
        )
        density = _density_curve_data(df, col_name, bins=effective_bins)
        if density["status"] == "ok":
            st.caption("Density (normalized histogram)")
            st.line_chart(density["data"].set_index("value")[["density"]])
        box = _boxplot_data(df, col_name)
        if box["status"] == "ok":
            st.caption("Boxplot")
            st.vega_lite_chart(
                box["data"],
                {
                    "mark": {"type": "boxplot", "extent": 1.5},
                    "encoding": {
                        "x": {"field": "value", "type": "quantitative", "title": col_name}
                    },
                },
                use_container_width=True,
            )
    else:
        st.info("Insufficient distinct values for distribution chart.")
    ecdf = _numeric_ecdf_data(df, col_name)
    if ecdf["status"] == "ok":
        st.caption("ECDF — shows the share of values less than or equal to each value.")
        st.line_chart(ecdf["data"].set_index("value")[["cumulative_probability"]])
    else:
        st.info("Insufficient data for ECDF.")
    outlier_stats = _iqr_outlier_summary(df, col_name)
    if outlier_stats is not None:
        st.caption(
            f"IQR: {outlier_stats['iqr']:.2f} | "
            f"Fences: [{outlier_stats['lower_fence']:.2f}, "
            f"{outlier_stats['upper_fence']:.2f}] | "
            f"Outliers: {outlier_stats['outlier_count']}"
        )
    _render_qq_diagnostic(st, df, col_name)


def _render_log_histogram(st: Any, data: pd.DataFrame, col_name: str) -> bool:
    """Render the existing histogram bins on a log-scaled value axis.

    Display-only: the same bounded bin counts are plotted, nothing is
    transformed or dropped. Returns False (and explains why) when any bin edge
    is zero or negative, since a log axis cannot represent those values.
    """
    if float(data["left"].min()) <= 0:
        st.info("Log scale needs strictly positive values; showing the linear histogram.")
        return False
    st.vega_lite_chart(
        data,
        {
            "mark": "bar",
            "encoding": {
                "x": {
                    "field": "left",
                    "type": "quantitative",
                    "title": col_name,
                    "scale": {"type": "log"},
                    "bin": {"binned": True},
                },
                "x2": {"field": "right"},
                "y": {"field": "count", "type": "quantitative", "title": "Count"},
                "tooltip": [
                    {"field": "bin", "type": "nominal"},
                    {"field": "count", "type": "quantitative"},
                ],
            },
        },
        use_container_width=True,
    )
    st.caption("Log-scaled value axis — a display change only; the bin counts are unchanged.")
    return True


def _render_qq_diagnostic(st: Any, df: pd.DataFrame, col_name: str) -> None:
    """Render the opt-in normal Q-Q visual diagnostic for one numeric column."""
    show = st.checkbox("Show Q-Q plot (normal reference)", key=_EDA_SHOW_QQ)
    if not show:
        return
    result = _qq_normal_data(df[col_name])
    if result["status"] != "ok":
        st.info(
            "Q-Q needs at least "
            f"{QQ_MIN_OBSERVATIONS} usable finite values with some variation in this column. "
            "For a formal distribution test, use Statistics Lab."
        )
        return
    layers: list[dict[str, Any]] = [
        {
            "data": {"values": result["reference"].to_dict("records")},
            "mark": {"type": "line", "color": "red"},
            "encoding": {
                "x": {"field": "theoretical_quantile", "type": "quantitative"},
                "y": {"field": "observed_value", "type": "quantitative"},
            },
        },
        {
            "mark": {"type": "point", "filled": True, "opacity": 0.6},
            "encoding": {
                "x": {
                    "field": "theoretical_quantile",
                    "type": "quantitative",
                    "title": "Theoretical normal quantile",
                },
                "y": {
                    "field": "observed_value",
                    "type": "quantitative",
                    "title": f"Observed {col_name}",
                },
            },
        },
    ]
    st.caption(f"Q-Q plot: {col_name} vs a normal reference line")
    st.vega_lite_chart(result["data"], {"layer": layers}, use_container_width=True)
    if result["sampled"]:
        st.caption(
            f"Plotted {result['points']:,} of {result['observations']:,} usable values "
            f"(evenly spaced by rank, capped at {QQ_MAX_POINTS:,} points)."
        )
    st.caption(_QQ_CAVEAT)


def _render_univariate_categorical(
    st: Any,
    df: pd.DataFrame,
    categorical_columns: list[Any],
    *,
    dataset_name: str | None = None,
) -> None:
    """Render the categorical top-values block with optional Other bucket."""
    st.subheader("Categorical top values")
    if not categorical_columns:
        st.info("No categorical columns to explore.")
        return
    col_name = st.selectbox("Select categorical column", categorical_columns)
    if col_name is None:
        return
    top_n = int(
        st.number_input(
            "Top categories",
            min_value=1,
            max_value=MAX_TOP_CATEGORIES,
            value=MAX_TOP_CATEGORIES,
            step=1,
        )
    )
    include_missing = st.checkbox("Include missing values")
    other_bucket = st.checkbox("Include Other bucket", key=EDA_CAT_OTHER_BUCKET)
    top = _categorical_top_frequency_data(
        df, col_name, n=top_n, include_missing=include_missing, other_bucket=other_bucket
    )
    if top["status"] != "ok":
        st.info("No usable values for this column.")
        return
    top_df = top["data"]
    st.caption(f"Top values (up to {top['top_n']})")
    st.bar_chart(top_df.set_index("category")[["count"]])
    with st.expander("Category frequency details"):
        st.dataframe(top_df, hide_index=True)
        _render_csv_actions(
            st,
            download_label="Download category values (CSV)",
            dataframe=top_df,
            file_name="eda_categories.csv",
            button_label="Save category values to workspace",
            key=_SAVE_CATEGORIES_BTN,
            artifact="eda_categories",
            dataset_name=dataset_name,
        )
    if other_bucket and top.get("other_count"):
        st.caption(
            f"Other bucket aggregates {top['other_count']} rows beyond the displayed categories."
        )
    _render_pareto(st, df, col_name, include_missing=include_missing, dataset_name=dataset_name)


def _pareto_unavailable_message(status: str) -> str:
    """Return the plain-language reason a Pareto view is unavailable."""
    if status == "near_unique":
        return (
            "Pareto is unavailable: this column is close to unique per row, so a "
            "concentration view would mostly expose individual values."
        )
    if status == "invalid_type":
        return "Pareto applies to categorical columns; pick a non-numeric column."
    return "Pareto is unavailable: no usable category values in this column."


def _render_pareto(
    st: Any,
    df: pd.DataFrame,
    col_name: Any,
    *,
    include_missing: bool,
    dataset_name: str | None = None,
) -> None:
    """Render the opt-in Pareto (count + cumulative share) view for a category column."""
    show = st.checkbox("Show Pareto view (cumulative share)", key=_EDA_SHOW_PARETO)
    if not show:
        return
    pareto = _pareto_category_data(df, col_name, include_missing=include_missing)
    if pareto["status"] != "ok":
        st.info(_pareto_unavailable_message(str(pareto["status"])))
        return
    data = pareto["data"]
    st.caption(
        f"Pareto: {pareto['displayed_categories']} bar(s), capped at {PARETO_MAX_CATEGORIES}"
    )
    st.vega_lite_chart(
        data,
        {
            "layer": [
                {
                    "mark": "bar",
                    "encoding": {
                        "x": {"field": "category", "type": "nominal", "sort": None, "title": None},
                        "y": {"field": "count", "type": "quantitative", "title": "Rows"},
                        "tooltip": [
                            {"field": "category", "type": "nominal"},
                            {"field": "count", "type": "quantitative", "title": "Rows"},
                            {"field": "pct", "type": "quantitative", "title": "Share %"},
                        ],
                    },
                },
                {
                    "mark": {"type": "line", "color": "red", "point": True},
                    "encoding": {
                        "x": {"field": "category", "type": "nominal", "sort": None},
                        "y": {
                            "field": "cumulative_pct",
                            "type": "quantitative",
                            "title": "Cumulative %",
                            "scale": {"domain": [0, 100]},
                        },
                        "tooltip": [
                            {"field": "category", "type": "nominal"},
                            {
                                "field": "cumulative_pct",
                                "type": "quantitative",
                                "title": "Cumulative %",
                            },
                        ],
                    },
                },
            ],
            "resolve": {"scale": {"y": "independent"}},
        },
        use_container_width=True,
    )
    if pareto["suppressed_categories"] or pareto["grouped_categories"]:
        st.caption(
            f"{pareto['suppressed_categories']} category value(s) with fewer than "
            f"{PARETO_MIN_CATEGORY_COUNT} rows and {pareto['grouped_categories']} beyond the "
            "cap were aggregated into the (other) bucket."
        )
    with st.expander("Pareto details"):
        st.dataframe(data, hide_index=True)
        _render_csv_actions(
            st,
            download_label="Download Pareto data (CSV)",
            dataframe=data,
            file_name="eda_pareto.csv",
            button_label="Save Pareto data to workspace",
            key=_SAVE_PARETO_BTN,
            artifact="eda_pareto",
            dataset_name=dataset_name,
        )
    st.caption(_PARETO_CAVEAT)


def _render_eda_univariate(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    """Render bounded numeric distributions and categorical top values."""
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    categorical_columns = [column for column in df.columns if column not in numeric_columns]
    _render_univariate_numeric(st, df, numeric_columns, dataset_name=dataset_name)
    _render_univariate_categorical(st, df, categorical_columns, dataset_name=dataset_name)


def _render_numeric_shape(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    """Render per-numeric-column skewness and kurtosis with a CSV download."""
    st.subheader("Distribution shape (skewness & kurtosis)")
    summary = _skew_kurtosis_summary(df)
    if summary.empty:
        st.info("No numeric columns to summarize.")
        return
    st.dataframe(summary, hide_index=True)
    _render_csv_actions(
        st,
        download_label="Download shape summary (CSV)",
        dataframe=summary,
        file_name="eda_skew_kurtosis.csv",
        button_label="Save shape summary to workspace",
        key=_SAVE_SKEW_KURTOSIS_BTN,
        artifact="eda_skew_kurtosis",
        dataset_name=dataset_name,
    )


def _select_correlation_columns(st: Any, df: pd.DataFrame) -> list[str]:
    """Return the operator-selected numeric columns for the correlation views.

    Uses ``st.multiselect`` when the runtime provides it; test doubles that omit
    the widget (like the ones in this repo's render tests) simply fall back to
    the deterministic default — the first ``NUMERIC_CORRELATION_MAX_COLUMNS``
    numeric columns — which is also what an empty selection means.
    """
    options = _numeric_correlation_columns(df, max_columns=MAX_SUMMARY_COLUMNS)
    if len(options) < 2:
        return []
    default = options[:NUMERIC_CORRELATION_MAX_COLUMNS]
    selector = getattr(st, "multiselect", None)
    if not callable(selector):
        return default
    chosen = (
        selector(
            f"Numeric columns to correlate (up to {NUMERIC_CORRELATION_MAX_COLUMNS})",
            options,
            default=default,
            key=_EDA_CORR_COLUMNS,
        )
        or []
    )
    selected = [str(column) for column in chosen][:NUMERIC_CORRELATION_MAX_COLUMNS]
    return selected or default


def _render_correlation_matrix(
    st: Any, df: pd.DataFrame, *, dataset_name: str | None = None
) -> dict[str, Any] | None:
    """Render the correlation heatmap/table; returns the builder result when drawn."""
    st.subheader("Correlation matrix")
    method_label = st.selectbox(
        "Correlation method", list(_CORR_METHOD_LABELS), key=EDA_CORR_METHOD
    )
    method = _CORR_METHOD_LABELS.get(method_label, "pearson")
    selected_columns = _select_correlation_columns(st, df)
    heatmap = _correlation_heatmap_data(df, method=method, selected_columns=selected_columns)
    if heatmap["status"] != "ok":
        st.info("Need at least two numeric columns for a correlation matrix.")
        return None
    heatmap_df = heatmap["data"]
    st.vega_lite_chart(
        heatmap_df,
        {
            "mark": "rect",
            "encoding": {
                "x": {"field": "x", "type": "nominal", "title": None},
                "y": {"field": "y", "type": "nominal", "title": None},
                "color": {
                    "field": "correlation",
                    "type": "quantitative",
                    "scale": {"domain": [-1, 1], "scheme": "redblue"},
                },
                "tooltip": [
                    {"field": "x", "type": "nominal"},
                    {"field": "y", "type": "nominal"},
                    {"field": "correlation", "type": "quantitative"},
                ],
            },
        },
        use_container_width=True,
    )
    with st.expander("Correlation table"):
        matrix = heatmap["matrix"]
        st.dataframe(matrix)
        correlation_export = matrix.reset_index()
        _render_csv_actions(
            st,
            download_label="Download correlation table (CSV)",
            dataframe=correlation_export,
            file_name="eda_correlation.csv",
            button_label="Save correlation table to workspace",
            key=_SAVE_CORRELATION_BTN,
            artifact="eda_correlation",
            dataset_name=dataset_name,
        )
    st.caption(f"Method: {str(heatmap['method']).title()}.")
    numeric_count = df.select_dtypes(include="number").shape[1]
    if numeric_count > MAX_CORRELATION_COLUMNS:
        st.caption(
            f"Correlation covers {heatmap['numeric_columns']} of {numeric_count} numeric columns "
            f"(cap: {MAX_CORRELATION_COLUMNS}). Adjust the column selection above to compare "
            "a different subset."
        )
    return heatmap


def _render_correlation_pairs(
    st: Any, heatmap: dict[str, Any] | None, *, dataset_name: str | None = None
) -> None:
    """Render the strongest numeric correlation pairs from an existing matrix.

    Consumes the result the correlation section already produced — the matrix is
    never recomputed — and shows ranked, de-duplicated pairs (upper triangle
    only, so the diagonal and mirrored duplicates cannot appear).
    """
    if heatmap is None or heatmap.get("status") != "ok":
        return
    show = st.checkbox("Show strongest correlated pairs", key=_EDA_SHOW_CORR_PAIRS)
    if not show:
        return
    pairs = heatmap.get("pairs")
    if pairs is None or pairs.empty:
        st.info("No comparable numeric pairs: every pair is constant or undefined.")
        return
    st.caption(f"Strongest pairs (top {len(pairs)}, {str(heatmap['method']).title()})")
    st.dataframe(pairs, hide_index=True)
    _render_csv_actions(
        st,
        download_label="Download correlated pairs (CSV)",
        dataframe=pairs,
        file_name="eda_correlation_pairs.csv",
        button_label="Save correlated pairs to workspace",
        key=_SAVE_CORRELATION_PAIRS_BTN,
        artifact="eda_correlation_pairs",
        dataset_name=dataset_name,
    )
    st.caption(_CORRELATION_PAIRS_CAVEAT)


def _categorical_association_columns(st: Any, df: pd.DataFrame) -> list[str]:
    """Return the operator-selected categorical columns for the association matrix."""
    options = [
        str(df.columns[position])
        for position in range(min(df.shape[1], MAX_SUMMARY_COLUMNS))
        if not pd.api.types.is_numeric_dtype(df.iloc[:, position])
    ]
    if len(options) < 2:
        return []
    default = options[:CATEGORICAL_ASSOC_MAX_COLUMNS]
    selector = getattr(st, "multiselect", None)
    if not callable(selector):
        return default
    chosen = (
        selector(
            f"Categorical columns to compare (up to {CATEGORICAL_ASSOC_MAX_COLUMNS})",
            options,
            default=default,
            key=_EDA_CAT_ASSOC_COLUMNS,
        )
        or []
    )
    selected = [str(column) for column in chosen][:CATEGORICAL_ASSOC_MAX_COLUMNS]
    return selected or default


def _render_categorical_association(
    st: Any, df: pd.DataFrame, *, dataset_name: str | None = None
) -> None:
    """Render the opt-in bounded categorical association matrix (corrected Cramér's V)."""
    st.subheader("Categorical association")
    show = st.checkbox("Show categorical association matrix", key=_EDA_SHOW_CAT_ASSOC)
    if not show:
        st.caption(
            "Optional: an exploratory effect-strength view of how categorical columns "
            "vary together. No hypothesis test is run."
        )
        return
    selected = _categorical_association_columns(st, df)
    result = _categorical_association_data(df, selected)
    if result["status"] != "ok":
        st.info(
            "Need at least two usable categorical columns. Constant, empty, and "
            "near-unique identifier-like columns are excluded."
        )
        _render_association_exclusions(st, result.get("unavailable"))
        return
    st.caption(
        f"Association strength (0-1) across {result['columns_displayed']} column(s), "
        f"levels capped at {CATEGORICAL_ASSOC_MAX_LEVELS} per column."
    )
    st.vega_lite_chart(
        result["data"],
        {
            "mark": "rect",
            "encoding": {
                "x": {"field": "x", "type": "nominal", "title": None},
                "y": {"field": "y", "type": "nominal", "title": None},
                "color": {
                    "field": "association",
                    "type": "quantitative",
                    "scale": {"domain": [0, 1], "scheme": "blues"},
                },
                "tooltip": [
                    {"field": "x", "type": "nominal"},
                    {"field": "y", "type": "nominal"},
                    {"field": "association", "type": "quantitative"},
                ],
            },
        },
        use_container_width=True,
    )
    pairs = result["pairs"]
    if not pairs.empty:
        with st.expander("Strongest categorical pairs"):
            st.dataframe(pairs, hide_index=True)
            _render_csv_actions(
                st,
                download_label="Download categorical association (CSV)",
                dataframe=pairs,
                file_name="eda_categorical_association.csv",
                button_label="Save categorical association to workspace",
                key=_SAVE_CATEGORICAL_ASSOC_BTN,
                artifact="eda_categorical_association",
                dataset_name=dataset_name,
            )
    if result["row_sampled"]:
        st.caption(
            f"Sample-derived: computed on {result['rows_used']:,} of "
            f"{result['source_rows']:,} rows (evenly spaced, deterministic; cap "
            f"{CATEGORICAL_ASSOC_MAX_ROWS:,})."
        )
    _render_association_exclusions(st, result.get("unavailable"))
    st.caption(_CATEGORICAL_ASSOC_CAVEAT)


_ASSOCIATION_EXCLUSION_LABELS = {
    "empty": "no non-missing values",
    "constant": "only one level",
    "near_unique": "identifier-like (near-unique values)",
    "column_cap": "beyond the column cap",
}


def _render_association_exclusions(st: Any, unavailable: Any) -> None:
    """Explain every categorical column the association matrix left out."""
    if not unavailable:
        return
    parts = [
        f"{entry['column']} ({_ASSOCIATION_EXCLUSION_LABELS.get(entry['reason'], entry['reason'])})"
        for entry in unavailable
    ]
    st.caption(f"Excluded columns: {', '.join(parts)}.")


def _render_outlier_summary(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    st.subheader("Outlier summary")
    chart = _outlier_bar_data(df)
    if chart["status"] != "ok":
        st.info("No numeric columns to summarize.")
        return
    chart_df = chart["data"]
    st.bar_chart(chart_df.set_index("column")[["outlier_count"]])
    with st.expander("Outlier details"):
        detail = _aggregate_iqr_outlier_summary(df)
        st.dataframe(detail, hide_index=True)
        _render_csv_actions(
            st,
            download_label="Download outlier data (CSV)",
            dataframe=detail,
            file_name="eda_outliers.csv",
            button_label="Save outlier data to workspace",
            key=_SAVE_OUTLIERS_BTN,
            artifact="eda_outliers",
            dataset_name=dataset_name,
        )
    numeric_count = df.select_dtypes(include="number").shape[1]
    if numeric_count > MAX_OUTLIER_COLUMNS:
        st.caption(
            f"Outlier summary is limited to the first {MAX_OUTLIER_COLUMNS} numeric columns."
        )


def _render_datetime_trend(st: Any, df: pd.DataFrame) -> None:
    st.subheader("Datetime trends")
    datetime_columns = _datetime_candidate_columns(df)
    if not datetime_columns:
        st.info("No datetime-like columns parsed confidently enough for a trend.")
        return
    datetime_col = st.selectbox("Select datetime column", datetime_columns)
    if datetime_col is None:
        return
    numeric_columns = df.select_dtypes(include="number").columns.tolist()
    metric_options = ["Row count", *numeric_columns]
    metric_label = st.selectbox("Trend metric", metric_options)
    metric = None if metric_label == "Row count" else metric_label
    granularity_label = st.selectbox(
        "Trend granularity", ["Day", "Week", "Month"], key=EDA_DT_GRANULARITY
    )
    granularity = str(granularity_label).lower() if granularity_label else "day"
    trend = _datetime_trend_data(df, datetime_col, metric, granularity=granularity)
    if trend["status"] == "ok":
        trend_df = trend["data"].set_index("timestamp")[["value"]]
        st.line_chart(trend_df)
        caption = (
            f"Parsed {trend['parse_ratio'] * 100:.1f}% of {datetime_col}; "
            f"metric: {trend['metric']}; granularity: {trend.get('granularity', granularity)}."
        )
        missing_dt = trend.get("missing_datetime")
        if missing_dt:
            caption += f" Missing datetime values: {missing_dt}."
        st.caption(caption)
        return
    if trend["status"] == "low_parse_confidence":
        st.info(
            f"Skipped trend: parsed {trend['parse_ratio'] * 100:.1f}% of values, "
            f"below the {DATETIME_PARSE_THRESHOLD * 100:.0f}% confidence threshold."
        )
    else:
        st.info("Not enough usable datetime values for a trend.")


def _num_num_vega_spec(
    col1: str,
    col2: str,
    *,
    x_domain: tuple[float, float] | None,
    y_domain: tuple[float, float] | None,
    use_log: bool,
    trend_records: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Build a Vega-Lite scatter spec with optional clipped/log axes and trend line."""
    x_scale: dict[str, Any] = {}
    y_scale: dict[str, Any] = {}
    if use_log:
        x_scale["type"] = "log"
        y_scale["type"] = "log"
    if x_domain is not None:
        x_scale["domain"] = list(x_domain)
    if y_domain is not None:
        y_scale["domain"] = list(y_domain)
    x_enc: dict[str, Any] = {"field": col1, "type": "quantitative", "title": col1}
    y_enc: dict[str, Any] = {"field": col2, "type": "quantitative", "title": col2}
    if x_scale:
        x_enc["scale"] = x_scale
    if y_scale:
        y_enc["scale"] = y_scale
    layers: list[dict[str, Any]] = [
        {
            "mark": {"type": "point", "filled": True, "opacity": 0.5},
            "encoding": {"x": x_enc, "y": y_enc},
        }
    ]
    if trend_records:
        layers.append(
            {
                "data": {"values": trend_records},
                "mark": {"type": "line", "color": "red"},
                "encoding": {
                    "x": {"field": col1, "type": "quantitative"},
                    "y": {"field": col2, "type": "quantitative"},
                },
            }
        )
    return {"layer": layers}


def _render_num_num_vega(
    st: Any,
    col1: str,
    col2: str,
    scatter: dict[str, Any],
    *,
    clip: bool,
    log_scale: bool,
    trend: bool,
) -> None:
    """Render the numeric-numeric scatter via Vega-Lite when a scale/trend control is on."""
    plotted = scatter["data"]
    use_log = False
    if log_scale:
        if bool((plotted[col1] > 0).all()) and bool((plotted[col2] > 0).all()):
            use_log = True
        else:
            st.info("Log scale needs strictly positive values on both axes; using linear scale.")
    trend_records: list[dict[str, Any]] | None = None
    if trend:
        trendline = scatter.get("trendline")
        if trendline is not None and not trendline.empty:
            trend_records = trendline.to_dict("records")
        else:
            st.info("Trend line unavailable for this column pair.")
    spec = _num_num_vega_spec(
        col1,
        col2,
        x_domain=scatter.get("x_domain") if clip else None,
        y_domain=scatter.get("y_domain") if clip else None,
        use_log=use_log,
        trend_records=trend_records,
    )
    st.vega_lite_chart(plotted, spec, use_container_width=True)


def _render_num_num_density(
    st: Any,
    df: pd.DataFrame,
    col1: str,
    col2: str,
    *,
    clip: bool,
    dataset_name: str | None = None,
) -> None:
    """Render a 2D binned-density heatmap (all rows, aggregated) below the scatter.

    Unlike the sampled scatter, this counts every finite row into a bounded bin
    grid, so dense regions read clearly on large datasets. Only aggregated bin
    counts reach the browser. Shares the scatter's ``clip`` control for its range.
    """
    density = _bounded_density_heatmap_data(df, col1, col2, clip=clip)
    if density["status"] != "ok":
        st.info("Insufficient distinct values for a density heatmap.")
        return
    data = density["data"]
    st.caption(
        f"2D binned density: {col1} vs {col2} — {density['total_count']:,} rows across "
        f"{density['bins_x']}×{density['bins_y']} bins ({density['nonzero_cells']} filled cells). "
        "Color and tooltip show the row count and share per cell."
    )
    st.vega_lite_chart(
        data,
        {
            "mark": "rect",
            "encoding": {
                "x": {
                    "field": "x_left",
                    "type": "quantitative",
                    "title": col1,
                    "bin": {"binned": True},
                },
                "x2": {"field": "x_right"},
                "y": {
                    "field": "y_left",
                    "type": "quantitative",
                    "title": col2,
                    "bin": {"binned": True},
                },
                "y2": {"field": "y_right"},
                "color": {"field": "count", "type": "quantitative", "title": "Count"},
                "tooltip": [
                    {"field": "count", "type": "quantitative", "title": "Count"},
                    {"field": "density", "type": "quantitative", "title": "Share", "format": ".2%"},
                    {"field": "x_left", "type": "quantitative", "title": f"{col1} ≥"},
                    {"field": "x_right", "type": "quantitative", "title": f"{col1} <"},
                    {"field": "y_left", "type": "quantitative", "title": f"{col2} ≥"},
                    {"field": "y_right", "type": "quantitative", "title": f"{col2} <"},
                ],
            },
        },
        use_container_width=True,
    )
    _render_csv_actions(
        st,
        download_label="Download density heatmap (CSV)",
        dataframe=data,
        file_name="eda_density_heatmap.csv",
        button_label="Save density heatmap to workspace",
        key=_SAVE_DENSITY_HEATMAP_BTN,
        artifact="eda_density_heatmap",
        dataset_name=dataset_name,
    )


def _render_num_num(
    st: Any, df: pd.DataFrame, col1: str, col2: str, *, dataset_name: str | None = None
) -> None:
    clip = st.checkbox("Clip axes to 1st–99th percentile", key=BIV_SCATTER_CLIP_AXES)
    log_scale = st.checkbox("Use log scale when both axes are positive", key=BIV_SCATTER_LOG_SCALE)
    trend = st.checkbox("Show linear trend line", key=BIV_SCATTER_TREND_LINE)
    show_density = st.checkbox("Show 2D binned density (heatmap)", key=BIV_DENSITY_HEATMAP)
    scatter = _bounded_scatter_data(df, col1, col2, clip=clip, trend=trend)
    if scatter["status"] != "ok":
        st.info("Insufficient distinct values for scatter chart.")
        return
    st.caption(f"Scatter: {col1} vs {col2}")
    if clip or log_scale or trend:
        _render_num_num_vega(st, col1, col2, scatter, clip=clip, log_scale=log_scale, trend=trend)
    else:
        st.scatter_chart(scatter["data"], x=col1, y=col2)
    if scatter["sampled"]:
        st.caption(f"Scatter sampled {scatter['plot_rows']:,} of {scatter['source_rows']:,} rows.")
    r = scatter["pearson_r"]
    if r is not None:
        st.caption(f"Pearson r: {r:.3f}")
    if show_density:
        _render_num_num_density(st, df, col1, col2, clip=clip, dataset_name=dataset_name)
    st.caption(_NUM_NUM_CAVEAT)


def _render_num_cat(
    st: Any,
    df: pd.DataFrame,
    num_col: str,
    cat_col: str,
    *,
    dataset_name: str | None = None,
) -> None:
    summary = _numeric_by_category_summary_data(df, num_col, cat_col)
    if summary["status"] != "ok":
        st.info("No usable data for this column pair.")
        return
    grouped = summary["data"]
    st.caption(f"{num_col} by {cat_col}")
    st.vega_lite_chart(
        grouped,
        {
            "height": {"step": 28},
            "layer": [
                {
                    "mark": "rule",
                    "encoding": {
                        "y": {"field": "category", "type": "nominal", "sort": "-x"},
                        "x": {"field": "min", "type": "quantitative", "title": num_col},
                        "x2": {"field": "max"},
                    },
                },
                {
                    "mark": {"type": "bar", "height": 12},
                    "encoding": {
                        "y": {"field": "category", "type": "nominal", "sort": "-x"},
                        "x": {"field": "q1", "type": "quantitative", "title": num_col},
                        "x2": {"field": "q3"},
                        "tooltip": [
                            {"field": "category", "type": "nominal"},
                            {"field": "count", "type": "quantitative"},
                            {"field": "mean", "type": "quantitative"},
                            {"field": "median", "type": "quantitative"},
                        ],
                    },
                },
                {
                    "mark": {"type": "tick", "color": "black", "thickness": 2},
                    "encoding": {
                        "y": {"field": "category", "type": "nominal", "sort": "-x"},
                        "x": {"field": "median", "type": "quantitative", "title": num_col},
                    },
                },
            ],
        },
        use_container_width=True,
    )
    with st.expander("Numeric by category details"):
        st.dataframe(grouped, hide_index=True)
        _render_csv_actions(
            st,
            download_label="Download numeric-by-category summary (CSV)",
            dataframe=grouped,
            file_name="eda_numeric_by_category.csv",
            button_label="Save numeric-by-category summary to workspace",
            key=_SAVE_NUMERIC_BY_CATEGORY_BTN,
            artifact="eda_numeric_by_category",
            dataset_name=dataset_name,
        )
    if summary["truncated"]:
        st.caption(
            f"Showing the top {MAX_GROUP_CATEGORIES} categories by row count "
            f"out of {summary['total_categories']}."
        )
    st.caption(_NUM_CAT_CAVEAT)


_CROSSTAB_NORMALIZE_LABELS: dict[str, str | None] = {
    "Counts": None,
    "Overall %": "overall",
    "Row %": "row",
    "Column %": "column",
}


def _render_cat_cat_heatmap(
    st: Any, df: pd.DataFrame, col1: str, col2: str, normalize: str | None
) -> None:
    """Render a Vega-Lite rect heatmap of the crosstab (raw or normalized)."""
    heatmap = _categorical_crosstab_heatmap_data(df, col1, col2, normalize=normalize)
    if heatmap["status"] != "ok":
        return
    st.caption("Crosstab heatmap")
    st.vega_lite_chart(
        heatmap["data"],
        {
            "mark": "rect",
            "encoding": {
                "x": {"field": "feature_x", "type": "nominal", "title": col1},
                "y": {"field": "feature_y", "type": "nominal", "title": col2},
                "color": {"field": "value", "type": "quantitative"},
                "tooltip": [
                    {"field": "feature_x", "type": "nominal"},
                    {"field": "feature_y", "type": "nominal"},
                    {"field": "value", "type": "quantitative"},
                    {"field": "count", "type": "quantitative"},
                ],
            },
        },
        use_container_width=True,
    )


def _render_cat_cat(
    st: Any,
    df: pd.DataFrame,
    col1: str,
    col2: str,
    *,
    dataset_name: str | None = None,
) -> None:
    normalize_label = st.selectbox(
        "Crosstab values", list(_CROSSTAB_NORMALIZE_LABELS), key=BIV_CROSSTAB_NORMALIZE
    )
    normalize = _CROSSTAB_NORMALIZE_LABELS.get(str(normalize_label))
    show_heatmap = st.checkbox("Show heatmap", key=BIV_CROSSTAB_HEATMAP)
    show_stacked = st.checkbox("Show 100% stacked comparison", key=_BIV_CROSSTAB_STACKED)
    result = _categorical_crosstab_data(df, col1, col2, normalize=normalize)
    if result["status"] != "ok":
        st.info("No usable data for this column pair.")
        return
    st.caption(f"Crosstab: {col1} vs {col2}")
    crosstab = result["data"]
    st.dataframe(crosstab)
    crosstab_export = crosstab.reset_index()
    _render_csv_actions(
        st,
        download_label="Download crosstab (CSV)",
        dataframe=crosstab_export,
        file_name="eda_crosstab.csv",
        button_label="Save crosstab to workspace",
        key=_SAVE_CROSSTAB_BTN,
        artifact="eda_crosstab",
        dataset_name=dataset_name,
    )
    if show_heatmap:
        _render_cat_cat_heatmap(st, df, col1, col2, normalize)
    if show_stacked:
        _render_cat_cat_stacked(st, df, col1, col2)
    if result["truncated"]:
        st.caption("Crosstab is capped to the most frequent categories.")
    st.caption(_CATEGORICAL_ASSOC_CAVEAT)


def _render_cat_cat_stacked(st: Any, df: pd.DataFrame, col1: str, col2: str) -> None:
    """Render a normalized 100% stacked comparison from the existing crosstab data.

    Shares reuse the row-normalized crosstab so the composition of ``col2``
    within each ``col1`` level is comparable even when the levels have very
    different sizes; the tooltip keeps the underlying group counts visible.
    """
    stacked = _categorical_crosstab_heatmap_data(df, col1, col2, normalize="row")
    if stacked["status"] != "ok":
        return
    st.caption(f"100% stacked: composition of {col2} within each {col1} level")
    st.vega_lite_chart(
        stacked["data"],
        {
            "mark": "bar",
            "encoding": {
                "x": {
                    "field": "value",
                    "type": "quantitative",
                    "title": f"Share of {col1} level (%)",
                    "stack": "normalize",
                },
                "y": {"field": "feature_x", "type": "nominal", "title": col1},
                "color": {"field": "feature_y", "type": "nominal", "title": col2},
                "tooltip": [
                    {"field": "feature_x", "type": "nominal", "title": col1},
                    {"field": "feature_y", "type": "nominal", "title": col2},
                    {"field": "count", "type": "quantitative", "title": "Rows"},
                    {"field": "value", "type": "quantitative", "title": "Row share %"},
                ],
            },
        },
        use_container_width=True,
    )
    st.caption("Shares hide group size — check the tooltip counts before comparing levels.")


def _swap_bivariate_columns(state: MutableMapping[str, Any], columns: Sequence[str]) -> None:
    """Exchange the bivariate column selections; no-op when either is missing or stale."""
    col1 = state.get(BIV_COL1)
    col2 = state.get(BIV_COL2)
    if col1 is None or col2 is None:
        return
    if col1 not in columns or col2 not in columns:
        return
    state[BIV_COL1], state[BIV_COL2] = col2, col1


def _step_bivariate_column(
    state: MutableMapping[str, Any],
    key: str,
    columns: Sequence[str],
    step: int,
) -> None:
    """Advance a bivariate selection by ``step`` with wraparound; no-op if missing/stale."""
    current = state.get(key)
    if current not in columns:
        return
    if not columns:
        return
    current_index = columns.index(current)
    state[key] = columns[(current_index + step) % len(columns)]


_BIV_GRANULARITY_LABELS = ["Day", "Week", "Month"]
_BIV_DT_AGG_LABELS: dict[str, str] = {
    "Mean": "mean",
    "Median": "median",
    "Sum": "sum",
    "Count": "count",
}


def _select_biv_granularity(st: Any) -> str:
    """Render the datetime-bivariate granularity selector and return day/week/month."""
    label = st.selectbox("Time granularity", _BIV_GRANULARITY_LABELS, key=BIV_DT_GRANULARITY)
    return str(label).lower() if label else "day"


def _dt_bivariate_info(st: Any, result: dict[str, Any]) -> None:
    """Render a safe info message for non-ok datetime-bivariate builder results."""
    if result["status"] == "low_parse_confidence":
        st.info(
            f"Skipped: datetime parsed below the {DATETIME_PARSE_THRESHOLD * 100:.0f}% "
            "confidence threshold."
        )
    else:
        st.info("Not enough usable data for this datetime pairing.")


def _render_dt_num(
    st: Any,
    df: pd.DataFrame,
    datetime_col: str,
    numeric_col: str,
    *,
    dataset_name: str | None = None,
) -> None:
    """Render a numeric column aggregated over datetime buckets (datetime is the time axis)."""
    granularity = _select_biv_granularity(st)
    agg_label = st.selectbox("Aggregation", list(_BIV_DT_AGG_LABELS), key=BIV_DT_NUM_AGG)
    aggregation = _BIV_DT_AGG_LABELS.get(str(agg_label), "mean")
    result = _datetime_numeric_aggregation_data(
        df, datetime_col, numeric_col, granularity=granularity, aggregation=aggregation
    )
    if result["status"] != "ok":
        _dt_bivariate_info(st, result)
        return
    st.caption(f"{numeric_col} by {datetime_col} ({aggregation}, {granularity})")
    st.line_chart(result["data"].set_index("period")[["value"]])
    _render_csv_actions(
        st,
        download_label="Download datetime aggregation (CSV)",
        dataframe=result["data"],
        file_name="eda_time_aggregation.csv",
        button_label="Save datetime aggregation to workspace",
        key=_SAVE_TIME_AGGREGATION_BTN,
        artifact="eda_time_aggregation",
        dataset_name=dataset_name,
    )
    st.caption(
        f"Rows used: {result['rows_used']:,}; missing datetime: {result['missing_datetime']:,}."
    )
    st.caption(_TIME_PAIR_CAVEAT)


def _render_dt_cat(
    st: Any,
    df: pd.DataFrame,
    datetime_col: str,
    categorical_col: str,
    *,
    dataset_name: str | None = None,
) -> None:
    """Render categorical counts over datetime buckets (datetime is the time axis)."""
    granularity = _select_biv_granularity(st)
    top_n = int(
        st.number_input(
            "Top categories",
            min_value=1,
            max_value=MAX_GROUP_CATEGORIES,
            value=MAX_GROUP_CATEGORIES,
            step=1,
            key=BIV_DT_CAT_TOP_N,
        )
    )
    result = _datetime_categorical_counts_data(
        df, datetime_col, categorical_col, granularity=granularity, top_n=top_n
    )
    if result["status"] != "ok":
        _dt_bivariate_info(st, result)
        return
    st.caption(f"{categorical_col} counts by {datetime_col} ({granularity})")
    st.vega_lite_chart(
        result["data"],
        {
            "mark": "line",
            "encoding": {
                "x": {"field": "period", "type": "temporal", "title": datetime_col},
                "y": {"field": "count", "type": "quantitative"},
                "color": {"field": "category", "type": "nominal", "title": categorical_col},
            },
        },
        use_container_width=True,
    )
    _render_csv_actions(
        st,
        download_label="Download datetime category counts (CSV)",
        dataframe=result["data"],
        file_name="eda_time_categories.csv",
        button_label="Save datetime category counts to workspace",
        key=_SAVE_TIME_CATEGORIES_BTN,
        artifact="eda_time_categories",
        dataset_name=dataset_name,
    )
    caption = (
        f"Categories plotted: {result['categories_plotted']}; "
        f"rows used: {result['rows_used']:,}; missing datetime: {result['missing_datetime']:,}."
    )
    if result.get("other_count"):
        caption += f" Other bucket: {result['other_count']}."
    st.caption(caption)
    st.caption(_TIME_PAIR_CAVEAT)


def _dispatch_bivariate(
    st: Any,
    df: pd.DataFrame,
    col1: str,
    col2: str,
    *,
    dataset_name: str | None = None,
) -> None:
    """Route a column pair to the type-aware bivariate renderer (datetime-aware)."""
    datetime_cols = set(_datetime_candidate_columns(df))
    dt1, dt2 = col1 in datetime_cols, col2 in datetime_cols
    n1 = pd.api.types.is_numeric_dtype(df[col1])
    n2 = pd.api.types.is_numeric_dtype(df[col2])
    if dt1 and not dt2:
        if n2:
            _render_dt_num(st, df, col1, col2, dataset_name=dataset_name)
        else:
            _render_dt_cat(st, df, col1, col2, dataset_name=dataset_name)
    elif dt2 and not dt1:
        if n1:
            _render_dt_num(st, df, col2, col1, dataset_name=dataset_name)
        else:
            _render_dt_cat(st, df, col2, col1, dataset_name=dataset_name)
    elif n1 and n2:
        _render_num_num(st, df, col1, col2, dataset_name=dataset_name)
    elif n1:
        _render_num_cat(st, df, col1, col2, dataset_name=dataset_name)
    elif n2:
        _render_num_cat(st, df, col2, col1, dataset_name=dataset_name)
    else:
        _render_cat_cat(st, df, col1, col2, dataset_name=dataset_name)


def _render_eda_bivariate(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    """Render EDA Bivariate Explorer: two-column selector, type-aware relationship view."""
    st.subheader("EDA — Bivariate Explorer")
    cols = df.columns.tolist()
    if len(cols) < 2:
        st.info("Need at least two columns for bivariate analysis.")
        return
    col1 = st.selectbox("First column", cols, key=BIV_COL1)
    col2 = st.selectbox("Second column", cols, key=BIV_COL2)
    # Test doubles may omit session_state; fall back to a throwaway mapping.
    st.button(
        "⇄ Swap X/Y",
        key=BIV_SWAP_BTN,
        on_click=_swap_bivariate_columns,
        args=(getattr(st, "session_state", {}), cols),
        help="Exchange the first and second column selections.",
    )
    st.button(
        "← Previous X",
        key=BIV_COL1_PREV_BTN,
        on_click=_step_bivariate_column,
        args=(getattr(st, "session_state", {}), BIV_COL1, cols, -1),
        help="Step the first column to the previous feature.",
    )
    st.button(
        "Next X →",
        key=BIV_COL1_NEXT_BTN,
        on_click=_step_bivariate_column,
        args=(getattr(st, "session_state", {}), BIV_COL1, cols, 1),
        help="Step the first column to the next feature.",
    )
    st.button(
        "← Previous Y",
        key=BIV_COL2_PREV_BTN,
        on_click=_step_bivariate_column,
        args=(getattr(st, "session_state", {}), BIV_COL2, cols, -1),
        help="Step the second column to the previous feature.",
    )
    st.button(
        "Next Y →",
        key=BIV_COL2_NEXT_BTN,
        on_click=_step_bivariate_column,
        args=(getattr(st, "session_state", {}), BIV_COL2, cols, 1),
        help="Step the second column to the next feature.",
    )
    if col1 == col2:
        st.info("Select two different columns.")
        return
    _dispatch_bivariate(st, df, col1, col2, dataset_name=dataset_name)


def _render_preprocessing_plan(st: Any, df: pd.DataFrame) -> None:
    """Point to Preprocess Studio, the canonical home for detailed recommendations.

    The full per-column recommendation table and recipe workflow live on the
    Preprocess Studio page; EDA Explorer keeps a concise pointer to avoid
    duplicating the same detailed rendering in two places.
    """
    st.subheader("Preprocessing Recommendations")
    st.caption(
        "Detailed preprocessing recommendations live in **Preprocess Studio**, where you can "
        "review per-column suggestions and build a reversible cleaning recipe."
    )


def render_overview_tab(
    st: Any,
    df: pd.DataFrame,
    result: dict[str, Any] | None,
    profile: Mapping[str, Any] | None,
    *,
    dataset_name: str | None = None,
) -> None:
    """Render the Overview tab sections."""
    st.caption(_OVERVIEW_TAB_INTRO)
    render_storylens_card(st, _eda_storylens(result, profile))
    _render_smart_guide(st, df)
    _render_dataset_profile(st, df, profile)
    _render_missingness(st, df, dataset_name=dataset_name)
    _render_structural_missingness(st, df, dataset_name=dataset_name)
    _render_duplicate_rows(st, df)
    _render_dtype_distribution(st, df)
    _render_preprocessing_plan(st, df)


def render_columns_tab(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    """Render the Columns tab sections."""
    st.caption(_COLUMNS_TAB_INTRO)
    _render_eda_univariate(st, df, dataset_name=dataset_name)


def render_relationships_tab(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    """Render the Relationships tab sections."""
    st.caption(_RELATIONSHIPS_TAB_INTRO)
    _render_eda_bivariate(st, df, dataset_name=dataset_name)


def render_time_tab(st: Any, df: pd.DataFrame) -> None:
    """Render the Time tab sections."""
    st.caption(_TIME_TAB_INTRO)
    _render_datetime_trend(st, df)


def render_advanced_tab(st: Any, df: pd.DataFrame, *, dataset_name: str | None = None) -> None:
    """Render the Advanced tab sections."""
    st.caption(_ADVANCED_TAB_INTRO)
    _render_numeric_shape(st, df, dataset_name=dataset_name)
    heatmap = _render_correlation_matrix(st, df, dataset_name=dataset_name)
    _render_correlation_pairs(st, heatmap, dataset_name=dataset_name)
    _render_categorical_association(st, df, dataset_name=dataset_name)
    _render_outlier_summary(st, df, dataset_name=dataset_name)


__all__ = [
    "_SAVE_CATEGORICAL_ASSOC_BTN",
    "_SAVE_CATEGORIES_BTN",
    "_SAVE_CORRELATION_BTN",
    "_SAVE_CORRELATION_PAIRS_BTN",
    "_SAVE_CROSSTAB_BTN",
    "_SAVE_DISTRIBUTION_BTN",
    "_SAVE_MISSINGNESS_BTN",
    "_SAVE_MISSING_ASSOC_BTN",
    "_SAVE_NUMERIC_BY_CATEGORY_BTN",
    "_SAVE_OUTLIERS_BTN",
    "_SAVE_PARETO_BTN",
    "_SAVE_SKEW_KURTOSIS_BTN",
    "_SAVE_TIME_AGGREGATION_BTN",
    "_SAVE_TIME_CATEGORIES_BTN",
    "_eda_storylens",
    "_render_categorical_association",
    "_render_correlation_matrix",
    "_render_correlation_pairs",
    "_render_dataset_profile",
    "_render_datetime_trend",
    "_render_dtype_distribution",
    "_render_duplicate_rows",
    "_render_eda_bivariate",
    "_render_eda_univariate",
    "_render_missingness",
    "_render_outlier_summary",
    "_render_structural_missingness",
    "_render_visual_guide",
    "render_advanced_tab",
    "render_columns_tab",
    "render_overview_tab",
    "render_relationships_tab",
    "render_time_tab",
]
