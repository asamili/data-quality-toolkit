"""Tests for the Statistics Lab descriptive tier (page + service)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab as _lab
from data_quality_toolkit.adapters.ui.pages.statistics_lab import (
    _MANAGED_FAIL_CLOSED_MESSAGE,
    _SAVE_ASSUMPTION_CHECKS_BTN,
    _SAVE_CATEGORICAL_ASSOCIATIONS_BTN,
    _SAVE_CONFIDENCE_INTERVALS_BTN,
    _SAVE_COVARIANCE_MATRIX_BTN,
    _SAVE_DESCRIPTIVE_STATISTICS_BTN,
    _SAVE_DISTRIBUTIONS_BTN,
    _SAVE_GROUPED_NUMERIC_BY_CATEGORY_BTN,
    _SAVE_POWER_SAMPLE_SIZE_BTN,
    _SAVE_TOP_CORRELATIONS_BTN,
    _SAVE_VIF_MULTICOLLINEARITY_BTN,
    _SAVE_WILCOXON_BTN,
    _STATS_ASSUMPTION_SHOW_GUIDANCE,
    _STATS_CI_SHOW_EVIDENCE,
    _STATS_DIST_CALCULATION,
    _STATS_DIST_SHOW_CURVE,
    _STATS_POWER_SHOW_CURVE,
    _STATS_TAB_LABELS,
    DISTRIBUTION_CURVE_MAX_POINTS,
    _render_assumption_checks,
    _render_categorical_mixed,
    _render_confidence_interval_result,
    _render_distribution_lookup,
    _render_multivariate,
    _render_numeric_stats,
    _render_power_analysis,
    _render_statistics_lab,
    _render_wilcoxon,
)
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as _mfl
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    ManagedTrustRoot,
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
    retire_managed_trust,
)
from data_quality_toolkit.adapters.ui.services.statistics import (
    column_type_overview,
    numeric_descriptive_stats,
)
from data_quality_toolkit.adapters.ui.services.statistics_eligibility import (
    STATS_CATEGORICAL_MAX_LEVELS,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT, SRC_WORKSPACE_ROOT

_PATCH_LOAD = "data_quality_toolkit.adapters.ui.pages.statistics_lab._load_df_and_assess"
_PATCH_STATS_PROFILE = "data_quality_toolkit.adapters.ui.pages.statistics_lab.statistics_profile"

_DF = pd.DataFrame(
    {
        "n": [1.0, 2.0, 3.0, 4.0, 5.0],
        "m": [10.0, 9.0, 8.0, 7.0, 6.0],
        "c": ["a", "b", "a", "c", "a"],
    }
)
_RESULT: dict[str, Any] = {"profile": {"rows": 5, "cols": 3}, "assessment": {"score": 1.0}}
_STATS_PROFILE_RESULT: dict[str, Any] = {
    "status": "ok",
    "profile": {"n_rows": 5, "n_columns": 3, "memory_mb": 0.001, "dtypes": {}, "missing": {}},
    "numeric_summary": [
        {
            "column": "n",
            "count": 5,
            "missing": 0,
            "missing_pct": 0.0,
            "mean": 3.0,
            "median": 3.0,
            "std": 1.5811,
            "min": 1.0,
            "max": 5.0,
            "skew": 0.0,
            "kurtosis": -1.2,
        }
    ],
}


class FakeSt:
    """Minimal Streamlit recorder supporting columns/selectbox/context use."""

    def __init__(
        self,
        session_state: dict[str, Any] | None = None,
        checkboxes: dict[str, bool] | None = None,
        choices: dict[str, Any] | None = None,
    ) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.clicks: dict[str, bool] = {}
        self.checkboxes = checkboxes or {}
        self.choices = choices or {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _rec(self, name: str, *a: Any, **k: Any) -> None:
        self.calls.append((name, a, k))

    def __getattr__(self, name: str) -> Any:
        def recorder(*a: Any, **k: Any) -> None:
            self._rec(name, *a, **k)

        return recorder

    def button(self, label: str, **k: Any) -> bool:
        self._rec("button", label, **k)
        return bool(self.clicks.get(k.get("key", label), False))

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [FakeSt() for _ in range(n)]

    def text_input(self, label: str, **k: Any) -> str:
        self._rec("text_input", label, **k)
        return self.text_values.get(label, str(k.get("value", "")))

    def selectbox(self, label: str, options: Any = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        key = k.get("key")
        if key in self.choices:
            return self.choices[key]
        return options[0] if options else None

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        return bool(self.checkboxes.get(str(k.get("key") or label), False))

    def tabs(self, labels: list[str]) -> list[FakeSt]:
        self._rec("tabs", labels)
        return [self for _ in labels]

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def call_count(self, name: str) -> int:
        return sum(1 for c in self.calls if c[0] == name)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))

    def charts(self) -> list[tuple[Any, ...]]:
        return [a for name, a, _k in self.calls if name == "vega_lite_chart"]


# ── service ─────────────────────────────────────────────────────────────────


def test_numeric_descriptive_stats_has_expected_columns() -> None:
    stats = numeric_descriptive_stats(_DF)
    assert stats is not None
    assert set(stats.columns) == {
        "count",
        "mean",
        "median",
        "std",
        "min",
        "max",
        "skew",
        "kurtosis",
    }
    assert "n" in stats.index
    assert "c" not in stats.index  # categorical excluded


def test_numeric_descriptive_stats_none_without_numeric() -> None:
    assert numeric_descriptive_stats(pd.DataFrame({"c": ["a", "b"]})) is None


def test_column_type_overview_counts() -> None:
    overview = column_type_overview(_DF)
    assert overview["total_columns"] == 3
    assert overview["numeric_columns"] == 2
    assert overview["categorical_or_other_columns"] == 1


# ── page render ────────────────────────────────────────────────────────────


def test_render_empty_path_shows_info() -> None:
    st = FakeSt()
    _render_statistics_lab(st, {})
    assert st.called("header")
    assert st.called("info")
    assert not st.called("dataframe")


def test_render_load_error_shows_error() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "bad.csv"
    with patch(_PATCH_LOAD, return_value=(None, None, "file not found")):
        _render_statistics_lab(st, {})
    assert st.called("error")
    assert not st.called("dataframe")


def test_render_happy_path_shows_descriptive_tables() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})
    assert st.called("dataframe")
    assert st.called("metric")  # dimension cards
    text = st.texts()
    assert "Descriptive Statistics / Profile" in text
    assert "Numeric descriptive statistics" in text
    # Inferential tier now renders below the descriptive tables.
    assert "Inferential Tests" in text


def test_render_happy_path_uses_task_tabs() -> None:
    """The loaded page organizes sections into the task-oriented tabs."""
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})
    tab_calls = [a[0] for name, a, _ in st.calls if name == "tabs"]
    assert tab_calls == [_STATS_TAB_LABELS]
    assert _STATS_TAB_LABELS == [
        "Overview",
        "Descriptive statistics",
        "Relationships",
        "Categories & groups",
        "Statistical tests",
        "Distributions",
        "Power & Sample size",
    ]


def test_render_happy_path_shows_tab_guidance_captions() -> None:
    """Each tab opens with a 'what this helps answer' guidance caption."""
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})
    text = st.texts()
    assert "healthy enough to analyze" in text
    assert "each column look like on its own" in text
    assert "move together" in text
    assert "differ across groups" in text
    assert "real or likely noise" in text
    assert "theoretical distribution imply" in text
    assert "how big a sample do I need" in text


def test_render_distribution_lookup_default_no_crash() -> None:
    st = FakeSt()
    fake_result = {
        "status": "ok",
        "reason": None,
        "distribution": "Normal",
        "calculation": "PDF",
        "parameters": {"x": 0.0, "mu": 0.0, "sigma": 1.0},
        "value": 0.3989422804,
        "method": "normal_pdf",
        "tail": None,
        "explanation": "Normal PDF evaluated at 0.0.",
    }
    with patch(
        "data_quality_toolkit.adapters.ui.pages.statistics_lab.theoretical_distribution_result",
        return_value=fake_result,
    ):
        _render_distribution_lookup(st)
    assert "Theoretical distributions" in st.texts()
    assert st.called("metric")
    assert st.called("dataframe")
    assert "statistics_distributions.csv" in _download_file_names(st)
    assert _SAVE_DISTRIBUTIONS_BTN in _button_keys(st)


def test_render_power_analysis_wires_download_and_workspace_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "data_quality_toolkit.adapters.ui.pages.statistics_lab.power_mean",
        lambda *_a, **_k: {
            "status": "ok",
            "reason": None,
            "method": "normal_power_mean",
            "power": 0.8123,
        },
    )
    st = FakeSt()
    _render_power_analysis(st)
    assert "statistics_power_sample_size.csv" in _download_file_names(st)
    assert _SAVE_POWER_SAMPLE_SIZE_BTN in _button_keys(st)


def test_render_empty_path_does_not_render_tabs() -> None:
    """Tabs appear only after a dataset is loaded; empty state stays flat."""
    st = FakeSt()
    _render_statistics_lab(st, {})
    assert not st.called("tabs")


def test_render_does_not_draw_charts() -> None:
    """Statistics Lab is tables-only; charts belong to EDA Explorer."""
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)):
        _render_statistics_lab(st, {})
    assert not st.called("bar_chart")
    assert not st.called("scatter_chart")
    assert not st.called("line_chart")


def test_render_large_file_context_blocks_without_loading() -> None:
    st = FakeSt()
    context = DatasetContext(
        source_path="C:/safe/data.csv",
        display_name="data.csv",
        size_bytes=10,
        modified_ns=1,
        large_file_mode=True,
    )
    with patch(_PATCH_LOAD) as load:
        _render_statistics_lab(st, {DATASET_CONTEXT: context})
    load.assert_not_called()
    assert st.called("warning")


# ── multivariate diagnostics ─────────────────────────────────────────────────


def _download_file_names(st: FakeSt) -> list[str]:
    return [
        k["file_name"] for name, _, k in st.calls if name == "download_button" and "file_name" in k
    ]


def _button_keys(st: FakeSt) -> list[str]:
    return [k["key"] for name, _, k in st.calls if name == "button" and "key" in k]


def _analysis_files(root: Path) -> list[str]:
    folder = root / "analysis"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_render_page_shows_multivariate_section() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})
    assert "Multivariate diagnostics" in st.texts()


def test_render_page_shows_statistics_csv_workspace_save_parity() -> None:
    full_output_df = _DF.assign(d=["x", "y", "x", "y", "x"])
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(full_output_df, _RESULT, None)),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})

    download_names = _download_file_names(st)
    for file_name in [
        "descriptive_statistics.csv",
        "covariance_matrix.csv",
        "vif_multicollinearity.csv",
        "top_correlations.csv",
        "categorical_associations.csv",
        "grouped_numeric_by_category.csv",
    ]:
        assert file_name in download_names
    button_keys = _button_keys(st)
    for key in [
        _SAVE_DESCRIPTIVE_STATISTICS_BTN,
        _SAVE_COVARIANCE_MATRIX_BTN,
        _SAVE_VIF_MULTICOLLINEARITY_BTN,
        _SAVE_TOP_CORRELATIONS_BTN,
        _SAVE_CATEGORICAL_ASSOCIATIONS_BTN,
        _SAVE_GROUPED_NUMERIC_BY_CATEGORY_BTN,
    ]:
        assert key in button_keys


def test_confidence_interval_result_wires_download_and_workspace_save() -> None:
    st = FakeSt()
    _render_confidence_interval_result(
        st,
        {
            "status": "ok",
            "reason": None,
            "method": "t",
            "confidence": 0.95,
            "point": 10.0,
            "lower": 8.5,
            "upper": 11.5,
            "n": 25,
            "interpretation": "mean interval",
        },
    )
    assert "statistics_intervals.csv" in _download_file_names(st)
    assert _SAVE_CONFIDENCE_INTERVALS_BTN in _button_keys(st)


def test_descriptive_workspace_save_click_writes_csv(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    st.clicks[_SAVE_DESCRIPTIVE_STATISTICS_BTN] = True

    _render_numeric_stats(st, _DF, _STATS_PROFILE_RESULT)

    assert _download_file_names(st) == ["descriptive_statistics.csv"]
    assert _button_keys(st) == [_SAVE_DESCRIPTIVE_STATISTICS_BTN]
    assert _analysis_files(tmp_path) == ["descriptive_statistics.csv"]
    saved = tmp_path / "analysis" / "descriptive_statistics.csv"
    assert "column,count,missing" in saved.read_text(encoding="utf-8")
    text = st.texts()
    assert "analysis/descriptive_statistics.csv" in text
    assert str(tmp_path) not in text


def test_render_multivariate_two_numeric_shows_tables_and_downloads() -> None:
    st = FakeSt()
    _render_multivariate(st, _DF)  # n, m numeric; c categorical
    assert st.call_count("dataframe") == 3  # covariance + VIF + top correlations
    assert _download_file_names(st) == [
        "covariance_matrix.csv",
        "vif_multicollinearity.csv",
        "top_correlations.csv",
    ]
    assert _button_keys(st) == [
        _SAVE_COVARIANCE_MATRIX_BTN,
        _SAVE_VIF_MULTICOLLINEARITY_BTN,
        _SAVE_TOP_CORRELATIONS_BTN,
    ]
    assert not st.called("info")


def test_render_multivariate_fewer_than_two_numeric_shows_info_no_crash() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "c"]})
    st = FakeSt()
    _render_multivariate(st, df)
    assert st.call_count("info") == 3  # covariance, VIF, top correlations all unavailable
    assert not st.called("dataframe")
    assert not st.called("download_button")


# ── categorical and mixed diagnostics ─────────────────────────────────────────

_CAT_MIXED_DF = pd.DataFrame(
    {
        "cat1": ["a", "a", "b", "b"],
        "cat2": ["x", "y", "x", "y"],
        "num": [1.0, 2.0, 3.0, 4.0],
    }
)


def test_render_page_shows_categorical_mixed_section() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})
    assert "Categorical and mixed diagnostics" in st.texts()


def test_render_categorical_mixed_renders_both_outputs_and_downloads() -> None:
    st = FakeSt()
    _render_categorical_mixed(st, _CAT_MIXED_DF)
    assert st.call_count("dataframe") == 2  # associations + grouped summary
    assert _download_file_names(st) == [
        "categorical_associations.csv",
        "grouped_numeric_by_category.csv",
    ]
    assert _button_keys(st) == [
        _SAVE_CATEGORICAL_ASSOCIATIONS_BTN,
        _SAVE_GROUPED_NUMERIC_BY_CATEGORY_BTN,
    ]
    assert not st.called("info")


def test_render_categorical_mixed_no_usable_data_shows_info_no_crash() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0], "m": [3.0, 4.0]})  # numeric only
    st = FakeSt()
    _render_categorical_mixed(st, df)
    assert st.call_count("info") == 2  # associations + grouped both unavailable
    assert not st.called("dataframe")
    assert not st.called("download_button")


def test_multivariate_workspace_save_buttons_do_not_write_on_render(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})

    _render_multivariate(st, _DF)
    _render_categorical_mixed(st, _CAT_MIXED_DF)

    assert _download_file_names(st) == [
        "covariance_matrix.csv",
        "vif_multicollinearity.csv",
        "top_correlations.csv",
        "categorical_associations.csv",
        "grouped_numeric_by_category.csv",
    ]
    assert _button_keys(st) == [
        _SAVE_COVARIANCE_MATRIX_BTN,
        _SAVE_VIF_MULTICOLLINEARITY_BTN,
        _SAVE_TOP_CORRELATIONS_BTN,
        _SAVE_CATEGORICAL_ASSOCIATIONS_BTN,
        _SAVE_GROUPED_NUMERIC_BY_CATEGORY_BTN,
    ]
    assert not (tmp_path / "analysis").exists()
    assert "Saved to workspace" not in st.texts()


def test_multivariate_workspace_save_blank_root_writes_nothing(tmp_path: Path) -> None:
    st = FakeSt()
    for key in (
        _SAVE_COVARIANCE_MATRIX_BTN,
        _SAVE_VIF_MULTICOLLINEARITY_BTN,
        _SAVE_TOP_CORRELATIONS_BTN,
        _SAVE_CATEGORICAL_ASSOCIATIONS_BTN,
        _SAVE_GROUPED_NUMERIC_BY_CATEGORY_BTN,
    ):
        st.clicks[key] = True

    _render_multivariate(st, _DF)
    _render_categorical_mixed(st, _CAT_MIXED_DF)

    assert not (tmp_path / "analysis").exists()
    text = st.texts()
    assert "Workspace Root" in text and "Start" in text
    assert "Saved to workspace" not in text


def test_multivariate_workspace_save_click_writes_each_output(tmp_path: Path) -> None:
    st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
    for key in (
        _SAVE_COVARIANCE_MATRIX_BTN,
        _SAVE_VIF_MULTICOLLINEARITY_BTN,
        _SAVE_TOP_CORRELATIONS_BTN,
        _SAVE_CATEGORICAL_ASSOCIATIONS_BTN,
        _SAVE_GROUPED_NUMERIC_BY_CATEGORY_BTN,
    ):
        st.clicks[key] = True

    _render_multivariate(st, _DF)
    _render_categorical_mixed(st, _CAT_MIXED_DF)

    assert _analysis_files(tmp_path) == [
        "categorical_associations.csv",
        "covariance_matrix.csv",
        "grouped_numeric_by_category.csv",
        "top_correlations.csv",
        "vif_multicollinearity.csv",
    ]
    text = st.texts()
    assert "analysis/covariance_matrix.csv" in text
    assert "analysis/vif_multicollinearity.csv" in text
    assert "analysis/top_correlations.csv" in text
    assert "analysis/categorical_associations.csv" in text
    assert "analysis/grouped_numeric_by_category.csv" in text
    assert str(tmp_path) not in text


def test_multivariate_workspace_save_repeated_save_suffixes(tmp_path: Path) -> None:
    for _ in range(2):
        st = FakeSt({SRC_WORKSPACE_ROOT: str(tmp_path)})
        st.clicks[_SAVE_COVARIANCE_MATRIX_BTN] = True
        _render_multivariate(st, _DF)

    assert _analysis_files(tmp_path) == ["covariance_matrix-1.csv", "covariance_matrix.csv"]


# ── assumption checks (informational display only) ────────────────────────────


class _GroupPickSt(FakeSt):
    """FakeSt that selects a specific value for the group selectbox."""

    def __init__(self, group_value: str, session_state: dict[str, Any] | None = None) -> None:
        super().__init__(session_state)
        self._group_value = group_value

    def selectbox(self, label: str, options: Any = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        if label == "Group by (optional)" and self._group_value in list(options):
            return self._group_value
        return options[0] if options else None


def test_render_assumption_checks_one_sample_wires_download_and_save() -> None:
    st = FakeSt()
    _render_assumption_checks(st, _DF, 0.05)
    text = st.texts()
    assert "Assumption checks" in text
    assert "informational" in text.lower()
    assert "statistics_assumption_checks.csv" in _download_file_names(st)
    assert _SAVE_ASSUMPTION_CHECKS_BTN in _button_keys(st)


def test_render_assumption_checks_grouped_no_crash() -> None:
    st = _GroupPickSt("cat1")
    _render_assumption_checks(st, _CAT_MIXED_DF, 0.05)
    assert "Assumption checks" in st.texts()
    assert "statistics_assumption_checks.csv" in _download_file_names(st)


def test_render_assumption_checks_no_numeric_shows_info() -> None:
    st = FakeSt()
    _render_assumption_checks(st, pd.DataFrame({"c": ["a", "b", "c"]}), 0.05)
    assert st.called("info")
    assert not st.called("download_button")


def test_render_assumption_checks_does_not_run_statistical_tests() -> None:
    """The panel is display-only: it must not invoke test-selection/verdict logic."""
    st = FakeSt()
    with (
        patch(
            "data_quality_toolkit.adapters.ui.pages.statistics_lab.select_hypothesis_test"
        ) as select,
        patch(
            "data_quality_toolkit.adapters.ui.pages.statistics_lab.run_two_sample_numeric_test"
        ) as run_two,
        patch(
            "data_quality_toolkit.adapters.ui.pages.statistics_lab.two_group_comparison"
        ) as two_group,
    ):
        _render_assumption_checks(st, _DF, 0.05)
    select.assert_not_called()
    run_two.assert_not_called()
    two_group.assert_not_called()


def test_loaded_page_includes_assumption_checks() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})
    assert "Assumption checks" in st.texts()


# ── Wilcoxon signed-rank (paired, user-selected option) ───────────────────────

_WILCOXON_SVC = "data_quality_toolkit.adapters.ui.pages.statistics_lab.paired_wilcoxon_test"


def test_render_wilcoxon_wires_download_and_save() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    _render_wilcoxon(st, _DF, 0.05)  # n, m numeric
    text = st.texts()
    assert "Wilcoxon signed-rank" in text
    assert "paired" in text.lower()
    assert "statistics_wilcoxon.csv" in _download_file_names(st)
    assert _SAVE_WILCOXON_BTN in _button_keys(st)


def test_render_wilcoxon_fewer_than_two_numeric_shows_info() -> None:
    st = FakeSt()
    _render_wilcoxon(st, pd.DataFrame({"n": [1.0, 2.0, 3.0], "c": ["a", "b", "c"]}), 0.05)
    assert st.called("info")
    assert not st.called("download_button")


def test_render_wilcoxon_unavailable_is_graceful() -> None:
    st = FakeSt()
    unavailable = {
        "status": "unavailable",
        "reason": "scipy is not installed",
        "test_name": "Wilcoxon signed-rank",
    }
    with patch(_WILCOXON_SVC, return_value=unavailable):
        _render_wilcoxon(st, _DF, 0.05)
    assert st.called("warning")
    assert not st.called("download_button")


def test_render_wilcoxon_does_not_run_test_selection() -> None:
    st = FakeSt()
    with (
        patch(
            "data_quality_toolkit.adapters.ui.pages.statistics_lab.select_hypothesis_test"
        ) as select,
        patch(
            "data_quality_toolkit.adapters.ui.pages.statistics_lab.run_two_sample_numeric_test"
        ) as run_two,
    ):
        _render_wilcoxon(st, _DF, 0.05)
    select.assert_not_called()
    run_two.assert_not_called()


def test_loaded_page_includes_wilcoxon() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})
    assert "Wilcoxon signed-rank" in st.texts()


# ── managed root-first dispatch ───────────────────────────────────────────────

_PATCH_MANAGED_FRAME = "data_quality_toolkit.adapters.ui.pages.statistics_lab.get_managed_frame"
_MANAGED_ABS = "C:\\workspace\\versions\\v1\\data.csv"


@pytest.fixture(autouse=True)
def _clean_managed_caches() -> Iterator[None]:
    _mfl.clear_managed_caches()
    yield
    _mfl.clear_managed_caches()


def _trusted_stats_session(
    *, large: bool = False, absolute: str = _MANAGED_ABS
) -> tuple[dict[str, Any], ManagedTrustRoot]:
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    root = commit_trust_root(
        state,
        capability,
        version_id=str(uuid.uuid4()),
        family_id=str(uuid.uuid4()),
        content_id="sha256:" + "a" * 64,
        root_content_id="sha256:" + "b" * 64,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name="data.csv",
            relative_posix="versions/v1/data.csv",
            absolute_path=absolute,
        ),
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=large,
    )
    return state, root


def _managed_mirror_stats_session() -> dict[str, Any]:
    return {
        DATASET_CONTEXT: DatasetContext(
            source_path=_MANAGED_ABS,
            display_name="data.csv",
            size_bytes=2048,
            modified_ns=10,
            managed=True,
            version_id=str(uuid.uuid4()),
            family_id=str(uuid.uuid4()),
            content_id="sha256:" + "a" * 64,
            root_content_id="sha256:" + "b" * 64,
            version_label="cleaned v2",
        )
    }


def _texts(st: FakeSt) -> str:
    return " ".join(str(x) for _, a, _ in st.calls for x in a if isinstance(x, str))


def test_managed_statistics_uses_managed_frame_not_legacy_loader() -> None:
    st = FakeSt()
    session, _root = _trusted_stats_session()
    with (
        patch(_PATCH_MANAGED_FRAME, return_value=_DF) as managed,
        patch(_PATCH_LOAD) as legacy,
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, session)
    managed.assert_called_once()
    legacy.assert_not_called()
    assert st.called("tabs")


def test_managed_statistics_profile_reads_trusted_locator() -> None:
    st = FakeSt()
    session, _root = _trusted_stats_session()
    with (
        patch(_PATCH_MANAGED_FRAME, return_value=_DF),
        patch(_PATCH_LOAD),
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT) as profile,
    ):
        _render_statistics_lab(st, session)
    profile.assert_called_once()
    assert profile.call_args[0][0] == _MANAGED_ABS


def test_managed_mirror_without_trust_fails_closed_in_statistics() -> None:
    st = FakeSt()
    with (
        patch(_PATCH_MANAGED_FRAME) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_statistics_lab(st, _managed_mirror_stats_session())
    managed.assert_not_called()
    legacy.assert_not_called()
    assert st.called("error")
    assert _MANAGED_FAIL_CLOSED_MESSAGE in _texts(st)
    assert not st.called("tabs")


def test_managed_large_statistics_refuses_frame_materialization() -> None:
    st = FakeSt()
    session, _root = _trusted_stats_session(large=True)
    with (
        patch(_PATCH_MANAGED_FRAME) as managed,
        patch(_PATCH_LOAD) as legacy,
    ):
        _render_statistics_lab(st, session)
    managed.assert_not_called()
    legacy.assert_not_called()
    assert st.called("warning")
    assert not st.called("tabs")


def test_manual_path_cannot_override_valid_trust_in_statistics() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "C:/manual/other.csv"
    session, _root = _trusted_stats_session()
    with (
        patch(_PATCH_MANAGED_FRAME, return_value=_DF) as managed,
        patch(_PATCH_LOAD) as legacy,
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, session)
    managed.assert_called_once()
    legacy.assert_not_called()
    assert not st.called("text_input")


def test_retired_trust_fails_closed_in_statistics() -> None:
    st = FakeSt()
    session, root = _trusted_stats_session()
    mirror = DatasetContext(
        source_path=_MANAGED_ABS,
        display_name="data.csv",
        size_bytes=root.size_bytes,
        modified_ns=root.modified_ns,
        managed=True,
        version_id=root.version_id,
        family_id=root.family_id,
        content_id=root.content_id,
        root_content_id=root.root_content_id,
        version_label=root.version_label,
    )
    retire_managed_trust(session)
    session[DATASET_CONTEXT] = mirror  # marker deliberately left behind
    with patch(_PATCH_MANAGED_FRAME) as managed:
        _render_statistics_lab(st, session)
    managed.assert_not_called()
    assert st.called("error")


def test_managed_loader_refusal_is_privacy_safe_in_statistics() -> None:
    st = FakeSt()
    session, _root = _trusted_stats_session()
    with patch(_PATCH_MANAGED_FRAME, side_effect=_mfl.ManagedFrameLoadError("SOURCE_MISSING")):
        _render_statistics_lab(st, session)
    assert st.called("error")
    text = _texts(st)
    assert _MANAGED_ABS not in text
    assert "C:\\workspace" not in text
    assert not st.called("tabs")


def test_unmanaged_statistics_flow_unchanged_without_trust() -> None:
    st = FakeSt()
    st.text_values["CSV path"] = "data.csv"
    with (
        patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)) as legacy,
        patch(_PATCH_MANAGED_FRAME) as managed,
        patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
    ):
        _render_statistics_lab(st, {})
    legacy.assert_called_once()
    managed.assert_not_called()
    assert st.called("tabs")


# ── opt-in distribution curve and assumption guidance ────────────────────


def test_distribution_curve_is_off_by_default() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    _render_distribution_lookup(st)

    assert not st.charts()
    assert _STATS_DIST_SHOW_CURVE in [
        k.get("key") for name, _a, k in st.calls if name == "checkbox"
    ]


def test_distribution_curve_is_bounded_and_marks_the_selected_value() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={_STATS_DIST_SHOW_CURVE: True})

    _render_distribution_lookup(st)

    data, spec = st.charts()[0]
    assert list(data.columns) == ["x", "value", "shaded"]
    assert len(data) <= DISTRIBUTION_CURVE_MAX_POINTS
    assert any("datum" in layer.get("encoding", {}).get("x", {}) for layer in spec["layer"])


def test_distribution_curve_shades_only_the_calculated_region() -> None:
    pytest.importorskip("scipy")
    density = FakeSt(checkboxes={_STATS_DIST_SHOW_CURVE: True})
    _render_distribution_lookup(density)  # default calculation is the PDF
    assert not bool(density.charts()[0][0]["shaded"].any())

    cumulative = FakeSt(
        checkboxes={_STATS_DIST_SHOW_CURVE: True},
        choices={_STATS_DIST_CALCULATION: "CDF"},
    )
    _render_distribution_lookup(cumulative)
    assert bool(cumulative.charts()[0][0]["shaded"].any())


def test_distribution_curve_states_its_theoretical_limit() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={_STATS_DIST_SHOW_CURVE: True})

    _render_distribution_lookup(st)

    text = st.texts()
    assert "makes no claim that the active dataset follows" in text
    assert "No goodness-of-fit test is performed here." in text


def test_distribution_curve_adds_no_second_lookup_result_or_artifact() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    on = FakeSt(checkboxes={_STATS_DIST_SHOW_CURVE: True})

    _render_distribution_lookup(off)
    _render_distribution_lookup(on)

    assert _download_file_names(on) == _download_file_names(off)
    assert _button_keys(on) == _button_keys(off)


def test_assumption_guidance_is_opt_in_and_never_gates_the_test() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    _render_assumption_checks(off, _DF, 0.05)
    assert "compliance score" not in off.texts()

    st = FakeSt(checkboxes={_STATS_ASSUMPTION_SHOW_GUIDANCE: True})
    _render_assumption_checks(st, _DF, 0.05)

    text = st.texts()
    assert "never switch the selected test" in text
    assert "compliance score" in text
    assert "rules of thumb" in text
    # The existing informational framing is preserved alongside the guidance.
    assert "These checks are informational" in text


def test_evidence_toggles_do_not_change_the_page_shell_or_artifacts() -> None:
    pytest.importorskip("scipy")

    def render(checkboxes: dict[str, bool]) -> FakeSt:
        st = FakeSt(checkboxes=checkboxes)
        st.text_values["CSV path"] = "data.csv"
        with (
            patch(_PATCH_LOAD, return_value=(_DF, _RESULT, None)),
            patch(_PATCH_STATS_PROFILE, return_value=_STATS_PROFILE_RESULT),
        ):
            _render_statistics_lab(st, {})
        return st

    off = render({})
    on = render(
        {
            _STATS_CI_SHOW_EVIDENCE: True,
            _STATS_DIST_SHOW_CURVE: True,
            _STATS_POWER_SHOW_CURVE: True,
            _STATS_ASSUMPTION_SHOW_GUIDANCE: True,
        }
    )

    assert [args for args in on.calls if args[0] == "tabs"] == [
        args for args in off.calls if args[0] == "tabs"
    ]
    assert _download_file_names(on) == _download_file_names(off)
    assert _button_keys(on) == _button_keys(off)
    assert on.called("vega_lite_chart")
    assert not off.called("vega_lite_chart")


# ── F2: bounded result-table rendering and centralized grouping policy ───────


def _numbered_frame(rows: int) -> pd.DataFrame:
    return pd.DataFrame(
        {"n": list(range(rows)), "label": [f"row_{index}" for index in range(rows)]}
    )


def _render_result_table(
    monkeypatch: pytest.MonkeyPatch, rows: int
) -> tuple[FakeSt, pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    frame = _numbered_frame(rows)
    downloads: dict[str, pd.DataFrame] = {}
    saves: dict[str, Any] = {}
    monkeypatch.setattr(
        _lab,
        "csv_download_button",
        lambda st, label, payload, name: downloads.update({name: payload}),
    )
    monkeypatch.setattr(
        _lab,
        "render_analysis_csv_save",
        lambda st, **kwargs: saves.update({kwargs["artifact"]: kwargs}),
    )
    st = FakeSt()
    _lab._render_downloadable_result_table(
        st,
        frame,
        download_label="Download",
        file_name="table.csv",
        save_label="Save",
        save_key="save_key",
        artifact="table",
        dataset_name="demo",
    )
    return st, frame, downloads, saves


def _only_rendered_frame(st: FakeSt) -> pd.DataFrame:
    frames = [a[0] for name, a, _k in st.calls if name == "dataframe"]
    assert len(frames) == 1
    return frames[0]


@pytest.mark.parametrize("rows", [499, 500])
def test_result_table_below_the_bound_renders_in_full(
    monkeypatch: pytest.MonkeyPatch, rows: int
) -> None:
    st, frame, downloads, saves = _render_result_table(monkeypatch, rows)
    assert len(_only_rendered_frame(st)) == rows
    assert len(downloads["table.csv"]) == rows
    assert len(saves["table"]["dataframe"]) == rows
    assert "Showing the first" not in st.texts()
    assert len(frame) == rows


@pytest.mark.parametrize(("rows", "disclosure"), [(501, "500 of 501"), (1_200, "500 of 1,200")])
def test_result_table_above_the_bound_previews_but_keeps_the_full_payload(
    monkeypatch: pytest.MonkeyPatch, rows: int, disclosure: str
) -> None:
    st, frame, downloads, saves = _render_result_table(monkeypatch, rows)
    rendered = _only_rendered_frame(st)
    assert len(rendered) == 500
    assert list(rendered["n"]) == list(range(500))
    assert len(downloads["table.csv"]) == rows
    assert len(saves["table"]["dataframe"]) == rows
    assert f"Showing the first {disclosure} rows." in st.texts()
    assert "Download or save the analysis for the complete table." in st.texts()
    assert len(frame) == rows
    assert list(frame["n"]) == list(range(rows))


def test_result_table_download_and_save_share_the_complete_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _st, frame, downloads, saves = _render_result_table(monkeypatch, 1_200)
    pd.testing.assert_frame_equal(downloads["table.csv"], frame)
    pd.testing.assert_frame_equal(saves["table"]["dataframe"], frame)


def test_group_candidate_columns_uses_the_centralized_policy_constant() -> None:
    assert _lab._MAX_GROUP_CARDINALITY == STATS_CATEGORICAL_MAX_LEVELS == 50


def test_group_candidate_columns_accepts_two_to_fifty_and_excludes_wider() -> None:
    rows = 204
    frame = pd.DataFrame(
        {
            "constant": ["only"] * rows,
            "binary": ["yes", "no"] * (rows // 2),
            "fifty": [f"level_{index % 50:05d}" for index in range(rows)],
            "fifty_one": [f"level_{index % 51:05d}" for index in range(rows)],
        }
    )
    assert _lab._group_candidate_columns(frame) == ["binary", "fifty"]
