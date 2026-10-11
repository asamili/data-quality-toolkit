"""Integration regression for the Statistics Lab high-cardinality payload defect (F2).

A deterministic synthetic dataset reproduces the D4 failure class: one near-unique
identifier column with 74,111 distinct values beside ordinary companion columns. The
whole Statistics Lab categorical family is driven through the existing fake render
double (no Streamlit server, no browser, no UAT), and the regression asserts the four
accepted policy layers together:

* the pathological variable never becomes eligible for a categorical workflow;
* no browser table receives more than 500 rows, while downloads and workspace saves
  still receive the complete result;
* no rendered caption, info state or warning enumerates an unbounded label set;
* no per-category widget is instantiated beyond the custom-proportion bound and no
  oversized contingency matrix is allocated.

The same scale also pins the nonparametric effect-size seam that the initial render
reaches automatically: Cliff's delta is counted exactly without pairs, and the exact
Hodges-Lehmann shift is reported as not computed instead of materializing ~1.3 billion
pairwise differences.

The reproduced cardinality (74,111) is the defect's own scale, so the regression is
run at that size and no larger.
"""

from __future__ import annotations

import tracemalloc
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab
from data_quality_toolkit.adapters.ui.pages import statistics_lab_chi_square as chi
from data_quality_toolkit.adapters.ui.pages import statistics_lab_runners as runners
from data_quality_toolkit.adapters.ui.services import statistics as svc
from data_quality_toolkit.adapters.ui.services.statistics_eligibility import (
    GOF_CUSTOM_PROPORTION_MAX_CATEGORIES,
    STATS_CATEGORICAL_MAX_LEVELS,
    STATS_TABLE_PREVIEW_MAX_ROWS,
)
from data_quality_toolkit.domain.statistics import effect_size

pytestmark = pytest.mark.integration

# The reproduced pathological cardinality from the accepted D4 evidence.
PATHOLOGICAL_LEVELS = 74_111

# A rendered string above this size is already a payload defect, not a caption.
_MAX_RENDERED_STRING = 2_000


class FakeSt:
    """Minimal Streamlit recorder with per-key selectbox/number_input control."""

    def __init__(
        self,
        choices: dict[str, Any] | None = None,
        numbers: dict[str, float] | None = None,
        checkboxes: dict[str, bool] | None = None,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.choices = choices or {}
        self.numbers = numbers or {}
        self.checkboxes = checkboxes or {}

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

    def columns(self, n: int) -> list[FakeSt]:
        self._rec("columns", n)
        return [FakeSt() for _ in range(n)]

    def selectbox(self, label: str, options: Any = (), **k: Any) -> Any:
        self._rec("selectbox", label, options, **k)
        opts = list(options)
        key = k.get("key")
        if key in self.choices:
            return self.choices[key]
        return opts[0] if opts else None

    def number_input(self, label: str, value: float = 0.0, **k: Any) -> Any:
        self._rec("number_input", label, value, **k)
        key = k.get("key")
        if key in self.numbers:
            return self.numbers[key]
        return value

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        return bool(self.checkboxes.get(str(k.get("key") or label), False))

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))

    def rendered_strings(self) -> list[str]:
        return [x for _n, a, _k in self.calls for x in a if isinstance(x, str)]

    def rendered_frames(self) -> list[pd.DataFrame]:
        return [a[0] for name, a, _k in self.calls if name == "dataframe" and a]

    def selectbox_options(self, key: str) -> list[Any] | None:
        for name, a, k in self.calls:
            if name == "selectbox" and k.get("key") == key and len(a) >= 2:
                return list(a[1])
        return None

    def widget_keys(self, name: str, prefix: str) -> list[str]:
        return [
            str(k.get("key"))
            for call, _a, k in self.calls
            if call == name and str(k.get("key", "")).startswith(prefix)
        ]


@pytest.fixture(scope="module")
def pathological_frame() -> pd.DataFrame:
    """Deterministic D4-class dataset: one near-unique field plus safe companions."""
    rows = PATHOLOGICAL_LEVELS
    return pd.DataFrame(
        {
            "record_id": [f"id_{index:06d}" for index in range(rows)],
            "outcome": ["yes" if index % 2 else "no" for index in range(rows)],
            "segment": [f"segment_{index % 40:03d}" for index in range(rows)],
            "region": [f"region_{index % 30:03d}" for index in range(rows)],
            "plan": [f"plan_{index % 45:03d}" for index in range(rows)],
            "channel": [f"channel_{index % 51:03d}" for index in range(rows)],
            "constant": ["only"] * rows,
        }
    )


_SAFE_CATEGORICAL = ["outcome", "segment", "region", "plan"]


def _capture(monkeypatch: pytest.MonkeyPatch, module: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    downloads: dict[str, Any] = {}
    saves: dict[str, Any] = {}
    monkeypatch.setattr(
        module,
        "csv_download_button",
        lambda st, label, payload, name: downloads.update({name: payload}),
    )
    monkeypatch.setattr(
        module,
        "render_analysis_csv_save",
        lambda st, **kwargs: saves.update({kwargs["artifact"]: kwargs}),
    )
    return downloads, saves


def _assert_bounded_rendering(st: FakeSt) -> None:
    """No browser table above the preview bound and no pathological rendered string."""
    for frame in st.rendered_frames():
        assert len(frame) <= STATS_TABLE_PREVIEW_MAX_ROWS
    for text in st.rendered_strings():
        assert len(text) <= _MAX_RENDERED_STRING, text[:200]
    joined = st.texts()
    assert "id_000001" not in joined
    assert "id_070000" not in joined


# ── L1 eligibility: the pathological variable never enters a workflow ─────────


def test_pathological_column_is_not_offered_for_goodness_of_fit(
    pathological_frame: pd.DataFrame,
) -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, pathological_frame, 0.05)
    assert st.selectbox_options(chi._GOF_COLUMN) == _SAFE_CATEGORICAL
    _assert_bounded_rendering(st)


def test_pathological_column_is_not_offered_for_contingency(
    pathological_frame: pd.DataFrame,
) -> None:
    for mode, first_key in (
        (chi._CHI_MODE_IND, chi._IND_FIRST_COLUMN),
        (chi._CHI_MODE_HOMOG, chi._HOMOG_OUTCOME_COLUMN),
    ):
        st = FakeSt(choices={chi._CHI_MODE_KEY: mode})
        chi.render_chi_square_tests_runner(st, pathological_frame, 0.05)
        assert st.selectbox_options(first_key) == _SAFE_CATEGORICAL
        _assert_bounded_rendering(st)


def test_pathological_column_is_not_offered_as_a_binary_outcome_or_group(
    pathological_frame: pd.DataFrame,
) -> None:
    st = FakeSt()
    runners.render_proportion_tests_runner(st, pathological_frame, 0.05)
    assert st.selectbox_options(runners._ONE_PROP_OUTCOME) == ["outcome"]
    _assert_bounded_rendering(st)

    two = FakeSt(choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO})
    runners.render_proportion_tests_runner(two, pathological_frame, 0.05)
    assert two.selectbox_options(runners._TWO_PROP_GROUP_COLUMN) == ["segment", "region", "plan"]
    _assert_bounded_rendering(two)


def test_pathological_column_is_refused_by_the_services_directly(
    pathological_frame: pd.DataFrame,
) -> None:
    """The service ceiling holds even when the page selector is bypassed entirely."""
    gof = svc.run_chi_square_gof_test(pathological_frame, "record_id")
    assert gof["status"] == "invalid_input"
    assert "categories" not in gof

    independence = svc.run_chi_square_independence_test(pathological_frame, "record_id", "outcome")
    assert independence["status"] == "invalid_input"
    assert "cells" not in independence

    proportion = svc.run_one_proportion_z_test(
        pathological_frame, "record_id", "id_000000", null_proportion=0.5
    )
    assert proportion["status"] == "invalid_input"
    assert "observed_values" not in proportion

    for result in (gof, independence, proportion):
        reason = str(result["reason"])
        assert "74,111" in reason
        assert "id_000001" not in reason
        assert len(reason) <= 200


def test_no_giant_contingency_matrix_is_allocated(
    pathological_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_a: object, **_k: object) -> object:
        raise AssertionError("an expected-count matrix was allocated for a rejected input")

    monkeypatch.setattr(svc, "_typed_categories", forbidden)
    monkeypatch.setattr(svc.np, "outer", forbidden)
    result = svc.run_chi_square_independence_test(pathological_frame, "record_id", "segment")
    assert result["status"] == "invalid_input"


# ── L2/L4: bounded widgets and bounded category text ─────────────────────────


def test_custom_proportion_widgets_stay_within_the_bound(
    pathological_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture(monkeypatch, chi)
    allowed = FakeSt(
        choices={
            chi._GOF_COLUMN: "segment",
            chi._GOF_EXPECTED_MODE: chi._GOF_EXPECTED_CUSTOM,
        }
    )
    chi.render_chi_square_tests_runner(allowed, pathological_frame, 0.05)
    widgets = allowed.widget_keys("number_input", chi._GOF_PROP_PREFIX)
    assert len(widgets) == 40
    assert len(widgets) <= GOF_CUSTOM_PROPORTION_MAX_CATEGORIES

    bounded = FakeSt(
        choices={
            chi._GOF_COLUMN: "plan",
            chi._GOF_EXPECTED_MODE: chi._GOF_EXPECTED_CUSTOM,
        }
    )
    chi.render_chi_square_tests_runner(bounded, pathological_frame, 0.05)
    assert bounded.widget_keys("number_input", chi._GOF_PROP_PREFIX) == []
    assert bounded.selectbox_options(chi._GOF_EXPECTED_MODE) == [chi._GOF_EXPECTED_EQUAL]
    assert "Custom expected proportions are available for up to 40 categories" in bounded.texts()
    _assert_bounded_rendering(bounded)


def test_category_captions_stay_bounded_for_wide_but_eligible_fields(
    pathological_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("scipy")
    _capture(monkeypatch, chi)
    st = FakeSt(choices={chi._GOF_COLUMN: "plan"})
    chi.render_chi_square_tests_runner(st, pathological_frame, 0.05)
    text = st.texts()
    assert "(+35 more)" in text
    assert "plan_044 [str]" not in text
    _assert_bounded_rendering(st)


# ── L3: bounded browser preview with an intact downloadable payload ──────────


def test_contingency_preview_is_bounded_while_the_download_stays_complete(
    pathological_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("scipy")
    downloads, saves = _capture(monkeypatch, chi)
    st = FakeSt(
        choices={
            chi._CHI_MODE_KEY: chi._CHI_MODE_IND,
            chi._IND_FIRST_COLUMN: "segment",
            chi._IND_SECOND_COLUMN: "region",
        }
    )
    chi.render_chi_square_tests_runner(st, pathological_frame, 0.05, dataset_name="d4")

    cells = downloads[chi._STATISTICS_IND_TABLE_FILE]
    assert len(cells) == 40 * 30
    saved = saves["statistics_chi_square_independence_table"]["dataframe"]
    pd.testing.assert_frame_equal(saved, cells)
    assert "Showing the first 500 of 1,200 rows." in st.texts()
    _assert_bounded_rendering(st)


def test_full_computation_is_unchanged_for_an_eligible_analysis(
    pathological_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("scipy")
    downloads, _saves = _capture(monkeypatch, chi)
    st = FakeSt(choices={chi._GOF_COLUMN: "segment"})
    chi.render_chi_square_tests_runner(st, pathological_frame, 0.05)

    rendered = downloads[chi._STATISTICS_GOF_FILE].iloc[0]
    direct = svc.run_chi_square_gof_test(pathological_frame, "segment", alpha=0.05)
    assert direct["status"] == "ok"
    assert rendered["statistic"] == pytest.approx(direct["statistic"])
    assert rendered["p_value"] == pytest.approx(direct["p_value"])
    assert rendered["degrees_of_freedom"] == direct["degrees_of_freedom"]
    assert rendered["reject_null"] == direct["reject_null"]
    counts = downloads[chi._STATISTICS_GOF_COUNTS_FILE]
    assert len(counts) == 40
    assert int(counts["observed_count"].sum()) == PATHOLOGICAL_LEVELS


# -- F6: a stale grouping selection never reaches category materialization --------
#
# ``FakeSt.selectbox`` honours ``choices`` by key and ignores the offered options, so
# pinning ``_TWO_PROP_GROUP_COLUMN`` to ``record_id`` or ``channel`` reproduces the
# stale or session-injected selection the two grouping guards exist for: neither column
# is ever offered by the selector itself.


def _record_typed_category_columns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the column of every ``_typed_categories`` call made during a render."""
    seen: list[str] = []
    original = svc._typed_categories

    def recorder(values: list[Any], column: str) -> Any:
        seen.append(column)
        return original(values, column)

    monkeypatch.setattr(svc, "_typed_categories", recorder)
    return seen


def _boundary_frame(levels: int) -> pd.DataFrame:
    """A binary outcome beside one grouping column of exactly *levels* distinct values."""
    rows = levels * 4
    return pd.DataFrame(
        {
            "outcome": ["yes" if index % 2 else "no" for index in range(rows)],
            "grp": [f"level_{index % levels:05d}" for index in range(rows)],
        }
    )


@pytest.mark.parametrize("stale_column", ["record_id", "channel"])
def test_stale_grouping_selection_materializes_no_categories(
    pathological_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch, stale_column: str
) -> None:
    seen = _record_typed_category_columns(monkeypatch)

    def forbidden(*_a: object, **_k: object) -> object:
        raise AssertionError("a refused grouping selection reached the statistical service")

    monkeypatch.setattr(runners, "run_two_proportion_z_test", forbidden)
    st = FakeSt(
        choices={
            runners._PROP_MODE_KEY: runners._PROP_MODE_TWO,
            runners._TWO_PROP_GROUP_COLUMN: stale_column,
        }
    )
    runners.render_proportion_tests_runner(st, pathological_frame, 0.05)

    assert stale_column not in seen
    assert st.selectbox_options(runners._TWO_PROP_GROUP_A) is None
    assert st.selectbox_options(runners._TWO_PROP_GROUP_B) is None
    assert st.selectbox_options(runners._TWO_PROP_ALTERNATIVE) is None
    messages = [str(a[0]) for name, a, _k in st.calls if name == "info" and a]
    assert messages
    assert max(len(message) for message in messages) < 400
    assert "channel_050" not in st.texts()
    _assert_bounded_rendering(st)


def test_group_category_options_refuses_pathological_columns_directly(
    pathological_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The helper guard holds when the page tier is bypassed entirely."""

    def forbidden(*_a: object, **_k: object) -> object:
        raise AssertionError("a refused grouping column reached _typed_categories")

    monkeypatch.setattr(svc, "_typed_categories", forbidden)
    for column, fragment in (("record_id", "identifier-like"), ("channel", "limited to 50")):
        options, error = svc.group_category_options(pathological_frame, column)
        assert options == []
        assert error is not None
        assert fragment in error
        assert "id_000001" not in error
        assert "channel_050" not in error
        assert len(error) <= 200


def test_group_category_options_still_serves_an_eligible_column(
    pathological_frame: pd.DataFrame,
) -> None:
    options, error = svc.group_category_options(pathological_frame, "segment")
    assert error is None
    assert len(options) == 40


@pytest.mark.parametrize(
    ("levels", "offered"),
    [(STATS_CATEGORICAL_MAX_LEVELS, True), (STATS_CATEGORICAL_MAX_LEVELS + 1, False)],
)
def test_grouping_boundary_is_pinned_end_to_end(levels: int, offered: bool) -> None:
    frame = _boundary_frame(levels)
    st = FakeSt(
        choices={
            runners._PROP_MODE_KEY: runners._PROP_MODE_TWO,
            runners._TWO_PROP_GROUP_COLUMN: "grp",
        }
    )
    runners.render_proportion_tests_runner(st, frame, 0.05)
    group_options = st.selectbox_options(runners._TWO_PROP_GROUP_A)
    if offered:
        assert st.selectbox_options(runners._TWO_PROP_GROUP_COLUMN) == ["grp"]
        assert group_options is not None
        assert len(group_options) == levels
    else:
        assert st.selectbox_options(runners._TWO_PROP_GROUP_COLUMN) is None
        assert group_options is None
        assert f"level_{levels - 1:05d}" not in st.texts()
    _assert_bounded_rendering(st)


def test_channel_column_sits_just_above_the_ceiling(
    pathological_frame: pd.DataFrame,
) -> None:
    """The 51-level companion pins the boundary the whole regression depends on."""
    assert pathological_frame["channel"].nunique() == STATS_CATEGORICAL_MAX_LEVELS + 1
    assert svc.run_chi_square_gof_test(pathological_frame, "channel")["status"] == "invalid_input"
    assert pathological_frame["plan"].nunique() == 45
    assert pathological_frame["record_id"].nunique() == PATHOLOGICAL_LEVELS


# -- R4: the nonparametric effect-size seam never builds the pairwise matrix -------
#
# The initial Statistics Lab render reaches Cliff's delta and the Hodges-Lehmann shift
# automatically for the first two-level grouping column. At the reproduced split
# (29,706 vs 44,405 rows) the exact Hodges-Lehmann kernel would materialize
# 1,319,094,930 pairwise differences (~9.8 GiB per float64 array).

_EFFECT_SPLIT = (29_706, 44_405)
_EFFECT_PAIRS = 1_319_094_930


class _PairwiseTripwire:
    """Stands in for ``numpy`` inside ``effect_size`` only; forbids ``np.subtract``."""

    def __init__(self) -> None:
        self.pairwise_calls = 0

    def __getattr__(self, name: str) -> Any:
        if name == "subtract":
            self.pairwise_calls += 1
            raise AssertionError("a full pairwise difference array was requested")
        return getattr(np, name)


@pytest.fixture(scope="module")
def effect_size_frame() -> pd.DataFrame:
    """74,111 rows: a near-unique id, a 29,706/44,405 two-level outcome, a measure."""
    rows = PATHOLOGICAL_LEVELS
    fail_rows = _EFFECT_SPLIT[0]
    # (index * 7919) % rows is a permutation of range(rows), so exactly fail_rows
    # interleaved rows land in the "fail" level.
    outcome = ["fail" if (index * 7_919) % rows < fail_rows else "pass" for index in range(rows)]
    return pd.DataFrame(
        {
            "record_id": [f"id_{index:06d}" for index in range(rows)],
            "outcome": outcome,
            "segment": [f"segment_{index % 4:03d}" for index in range(rows)],
            "channel": [f"channel_{index % 51:03d}" for index in range(rows)],
            "measure": [round(((index * 37) % 1_000) / 7.0, 3) for index in range(rows)],
        }
    )


def _arm_pairwise_tripwire(monkeypatch: pytest.MonkeyPatch) -> _PairwiseTripwire:
    tripwire = _PairwiseTripwire()
    monkeypatch.setattr(effect_size, "np", tripwire)
    return tripwire


def _assert_hodges_lehmann_not_computed(result: dict[str, Any]) -> None:
    assert result["status"] == "ok"
    assert (result["n_a"], result["n_b"]) == _EFFECT_SPLIT
    assert result["n_a"] * result["n_b"] == _EFFECT_PAIRS
    hodges_lehmann = result["hodges_lehmann"]
    assert hodges_lehmann["status"] == effect_size.PAIRWISE_LIMIT_STATUS
    assert hodges_lehmann["reason"] == effect_size.PAIRWISE_LIMIT_REASON
    assert hodges_lehmann["estimate"] is None
    assert hodges_lehmann["lower"] is None
    assert hodges_lehmann["upper"] is None


def test_effect_size_frame_reproduces_the_confirmed_split(
    effect_size_frame: pd.DataFrame,
) -> None:
    assert len(effect_size_frame) == PATHOLOGICAL_LEVELS
    assert effect_size_frame["outcome"].value_counts().to_dict() == {
        "pass": _EFFECT_SPLIT[1],
        "fail": _EFFECT_SPLIT[0],
    }
    assert effect_size_frame["record_id"].nunique() == PATHOLOGICAL_LEVELS
    assert effect_size_frame["channel"].nunique() == STATS_CATEGORICAL_MAX_LEVELS + 1
    fail, passed = (
        effect_size_frame.loc[effect_size_frame["outcome"] == level, "measure"]
        for level in ("fail", "pass")
    )
    assert effect_size.pairwise_comparison_count(fail, passed) == _EFFECT_PAIRS


def test_initial_inferential_render_bounds_the_effect_size_seam(
    effect_size_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The automatic render path reaches the bounded logic and never the pairwise kernel."""
    pytest.importorskip("scipy")
    tripwire = _arm_pairwise_tripwire(monkeypatch)
    results: list[dict[str, Any]] = []
    original = statistics_lab.nonparametric_effect_sizes

    def recorder(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(statistics_lab, "nonparametric_effect_sizes", recorder)
    st = FakeSt()

    statistics_lab._render_inferential(st, effect_size_frame, dataset_name="d4")

    assert tripwire.pairwise_calls == 0
    assert len(results) == 1
    result = results[0]
    assert (result["group_a"], result["group_b"]) == ("fail", "pass")
    _assert_hodges_lehmann_not_computed(result)
    fail = effect_size_frame.loc[effect_size_frame["outcome"] == "fail", "measure"]
    passed = effect_size_frame.loc[effect_size_frame["outcome"] == "pass", "measure"]
    assert result["cliffs_delta"] == round(effect_size.cliffs_delta(fail, passed), 6)
    limit_messages = [
        str(a[0]) for name, a, _k in st.calls if name == "info" and a and "pairwise" in str(a[0])
    ]
    assert len(limit_messages) == 1
    assert "1,000,000 pairwise differences" in limit_messages[0]
    assert len(limit_messages[0]) < 300
    _assert_bounded_rendering(st)


def test_effect_size_service_stays_bounded_in_memory_at_the_defect_scale(
    effect_size_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("scipy")
    tripwire = _arm_pairwise_tripwire(monkeypatch)

    tracemalloc.start()
    try:
        result = svc.nonparametric_effect_sizes(effect_size_frame, "measure", "outcome")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert tripwire.pairwise_calls == 0
    # A single pairwise float64 array at this split would be ~9.8 GiB.
    assert peak < 64 * 1024 * 1024
    assert -1.0 <= result["cliffs_delta"] <= 1.0
    _assert_hodges_lehmann_not_computed(result)
