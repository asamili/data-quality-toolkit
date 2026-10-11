"""Tests for the Statistics Lab chi-square Goodness-of-fit runner render (page tier).

A ``FakeSt`` recorder drives per-key selectbox/number_input choices so the goodness-of-fit
mode, the equal/custom expected-distribution branches, and the collision-safety paths can
be exercised. The runner routes computation through the service wrapper (never the domain
kernel directly), presents type-safe category options with disambiguated labels, states
right-tail semantics and the null/alternative question, degrades to a structured warning
when scipy is absent, and renders agreeing summary/evidence download and workspace-save
payloads. The existing PAIRED_T, Wilcoxon, and proportion panels stay present and distinct.
"""

from __future__ import annotations

import inspect
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab_chi_square as chi
from data_quality_toolkit.adapters.ui.pages.statistics_lab import _render_inferential
from data_quality_toolkit.adapters.ui.services import statistics as svc


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

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))

    def charts(self) -> list[tuple[Any, ...]]:
        return [a for name, a, _k in self.calls if name == "vega_lite_chart"]

    def selectbox_options(self, key: str) -> list[Any] | None:
        for name, a, k in self.calls:
            if name == "selectbox" and k.get("key") == key and len(a) >= 2:
                return list(a[1])
        return None


def _gof_df() -> pd.DataFrame:
    return pd.DataFrame({"cat": ["a"] * 30 + ["b"] * 30 + ["c"] * 40})


def _capture_downloads(monkeypatch: pytest.MonkeyPatch) -> dict[str, pd.DataFrame]:
    captured: dict[str, pd.DataFrame] = {}

    def fake_download(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
        captured[file_name] = df

    monkeypatch.setattr(chi, "csv_download_button", fake_download)
    return captured


# ── section + mode ────────────────────────────────────────────────────────────


def test_section_renders_with_right_tail_and_null_wording() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)
    text = st.texts()
    assert "Chi-square tests" in text
    assert "right-tail" in text.lower()
    assert "null" in text.lower()
    assert "alternative" in text.lower()


def test_goodness_of_fit_mode_is_offered() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)
    modes = st.selectbox_options(chi._CHI_MODE_KEY) or []
    assert chi._CHI_MODE_GOF in modes


# ── goodness of fit: equal proportions ────────────────────────────────────────


def test_gof_equal_success_renders_summary_and_counts() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)
    assert st.called("dataframe")
    assert st.called("download_button")


def test_gof_equal_download_payloads_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured = _capture_downloads(monkeypatch)
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05, dataset_name="demo")

    summary = captured[chi._STATISTICS_GOF_FILE].iloc[0]
    assert summary["test"] == "CHI_GOF"
    assert summary["expected_mode"] == "equal"
    assert summary["category_count"] == 3
    assert summary["valid_rows"] == 100
    assert summary["degrees_of_freedom"] == 2
    assert summary["status"] == "ok"

    counts = captured[chi._STATISTICS_GOF_COUNTS_FILE]
    assert list(counts["category"]) == ["a [str]", "b [str]", "c [str]"]
    assert list(counts["observed_count"]) == [30, 30, 40]
    assert list(counts["expected_count"]) == pytest.approx([100 / 3, 100 / 3, 100 / 3])


def test_gof_workspace_save_matches_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    downloads = _capture_downloads(monkeypatch)
    saves: dict[str, dict[str, Any]] = {}

    def fake_save(st: Any, **kwargs: Any) -> None:
        saves[kwargs["artifact"]] = kwargs

    monkeypatch.setattr(chi, "render_analysis_csv_save", fake_save)
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05, dataset_name="demo")

    assert set(saves) == {"statistics_chi_square_gof", "statistics_chi_square_gof_counts"}
    for save in saves.values():
        assert save["dataset_name"] == "demo"
    pd.testing.assert_frame_equal(
        saves["statistics_chi_square_gof"]["dataframe"], downloads[chi._STATISTICS_GOF_FILE]
    )
    pd.testing.assert_frame_equal(
        saves["statistics_chi_square_gof_counts"]["dataframe"],
        downloads[chi._STATISTICS_GOF_COUNTS_FILE],
    )


# ── goodness of fit: custom proportions ───────────────────────────────────────


def test_gof_custom_proportions_success(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured = _capture_downloads(monkeypatch)
    st = FakeSt(
        choices={chi._GOF_EXPECTED_MODE: chi._GOF_EXPECTED_CUSTOM},
        numbers={
            f"{chi._GOF_PROP_PREFIX}0": 0.3,
            f"{chi._GOF_PROP_PREFIX}1": 0.3,
            f"{chi._GOF_PROP_PREFIX}2": 0.4,
        },
    )
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)
    summary = captured[chi._STATISTICS_GOF_FILE].iloc[0]
    assert summary["expected_mode"] == "custom"
    assert summary["status"] == "ok"
    counts = captured[chi._STATISTICS_GOF_COUNTS_FILE]
    assert list(counts["expected_count"]) == pytest.approx([30.0, 30.0, 40.0])


def test_gof_custom_proportions_not_summing_renders_info() -> None:
    st = FakeSt(
        choices={chi._GOF_EXPECTED_MODE: chi._GOF_EXPECTED_CUSTOM},
        numbers={
            f"{chi._GOF_PROP_PREFIX}0": 0.5,
            f"{chi._GOF_PROP_PREFIX}1": 0.5,
            f"{chi._GOF_PROP_PREFIX}2": 0.5,
        },
    )
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)
    assert st.called("info")
    assert "sum to 1" in st.texts()


# ── goodness of fit: guidance + typed categories ──────────────────────────────


def test_gof_single_category_renders_info() -> None:
    df = pd.DataFrame({"cat": ["a", "a", "a"]})
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, df, 0.05)
    assert st.called("info")
    assert "at least two distinct" in st.texts()


def test_gof_colliding_labels_are_visibly_distinct() -> None:
    df = pd.DataFrame({"cat": pd.Series([1, "1", 1, "1", 2], dtype=object)})
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, df, 0.05)
    text = st.texts()
    assert "1 [int]" in text
    assert "1 [str]" in text


def test_gof_unresolved_collision_renders_warning() -> None:
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
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, df, 0.05)
    assert st.called("warning")
    assert st.selectbox_options(chi._GOF_EXPECTED_MODE) is None
    text = st.texts()
    assert "Traceback" not in text
    assert "0x" not in text


def test_gof_opaque_object_renders_warning_without_address() -> None:
    df = pd.DataFrame({"cat": pd.Series([object(), "ok"], dtype=object)})
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, df, 0.05)
    assert st.called("warning")
    assert "0x" not in st.texts()
    assert "object at" not in st.texts().lower()


def test_gof_scipy_unavailable_structured_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)  # must not raise
    assert st.called("warning")
    assert "Traceback" not in st.texts()
    assert "object at 0x" not in st.texts()


# ── architecture + page integration ───────────────────────────────────────────


def test_no_direct_domain_import_in_chi_module() -> None:
    assert "data_quality_toolkit.domain" not in inspect.getsource(chi)


def test_chi_module_does_not_call_scipy_directly() -> None:
    source = inspect.getsource(chi)
    assert "import scipy" not in source
    assert "scipy." not in source


def test_inferential_page_renders_chi_section_once_with_existing_runners() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "grp": ["x", "y"] * 15,
            "cat": (["a", "b", "c"] * 10),
            "before": np.random.default_rng(0).normal(10, 2, 30),
            "after": np.random.default_rng(1).normal(12, 2, 30),
        }
    )
    st = FakeSt()
    _render_inferential(st, df, dataset_name=None)
    text = st.texts()
    assert "Chi-square tests" in text
    assert text.count("Chi-square tests") == 1
    assert "Paired samples — parametric t-test" in text
    assert "Wilcoxon signed-rank" in text
    assert "Proportion tests" in text


# ── opt-in goodness-of-fit evidence (owner contract) ──────────────────────


def test_gof_evidence_is_off_by_default_and_owned_by_this_module() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)

    assert not st.charts()
    assert chi._GOF_SHOW_EVIDENCE in [
        k.get("key") for name, _a, k in st.calls if name == "checkbox"
    ]


def test_gof_evidence_renders_observed_versus_expected_bars() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)

    data, spec = st.charts()[0]
    assert list(data.columns) == ["category", "measure", "count"]
    assert set(data["category"]) == {"a [str]", "b [str]", "c [str]"}
    assert set(data["measure"]) == {"observed", "expected"}
    assert spec["mark"]["type"] == "bar"


def test_gof_evidence_reports_contributions_using_the_result_counts() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)

    frames = [
        args[0]
        for name, args, kwargs in st.calls
        if name == "dataframe" and "contribution" in getattr(args[0], "columns", [])
    ]
    assert frames
    evidence = frames[0]
    assert list(evidence["observed"]) == [30, 30, 40]
    assert list(evidence["expected"]) == pytest.approx([100 / 3] * 3, rel=1e-5)
    assert list(evidence["contribution_share"]) == pytest.approx([1 / 6, 1 / 6, 2 / 3], rel=1e-5)


def test_gof_evidence_carries_the_localisation_caveat_and_guidance() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)

    text = st.texts()
    assert "does not explain why they disagree" in text
    assert "What was compared" in text
    assert "What this does not show" in text


def test_gof_evidence_does_not_rerun_the_test_or_add_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    calls: list[int] = []
    original = chi.run_chi_square_gof_test

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(chi, "run_chi_square_gof_test", counting)
    saves: list[str] = []
    monkeypatch.setattr(
        chi, "render_analysis_csv_save", lambda _st, **kwargs: saves.append(kwargs["artifact"])
    )
    st = FakeSt(checkboxes={chi._GOF_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)

    assert len(calls) == 1
    assert saves == ["statistics_chi_square_gof", "statistics_chi_square_gof_counts"]


# ── F2: high-cardinality eligibility, bounded captions and bounded rendering ──


def _levels_df(levels: int, *, repeats: int = 4, column: str = "cat") -> pd.DataFrame:
    """A column with exactly *levels* distinct categories, each repeated *repeats* times."""
    return pd.DataFrame(
        {column: [f"level_{index:05d}" for index in range(levels) for _ in range(repeats)]}
    )


def _near_unique_df(levels: int, *, column: str = "cat") -> pd.DataFrame:
    """A column whose every row is a distinct value (identifier-like)."""
    return pd.DataFrame({column: [f"id_{index:06d}" for index in range(levels)]})


def _mixed_cardinality_df() -> pd.DataFrame:
    rows = 240
    return pd.DataFrame(
        {
            "binary": ["yes", "no"] * (rows // 2),
            "fifty": [f"level_{index % 50:05d}" for index in range(rows)],
            "fifty_one": [f"level_{index % 51:05d}" for index in range(rows)],
            "identifier": [f"id_{index:06d}" for index in range(rows)],
            "constant": ["only"] * rows,
        }
    )


def _prop_widget_keys(st: FakeSt) -> list[str]:
    return [
        str(k.get("key"))
        for name, _a, k in st.calls
        if name == "number_input" and str(k.get("key", "")).startswith(chi._GOF_PROP_PREFIX)
    ]


def test_gof_selector_offers_only_eligible_categorical_columns() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _mixed_cardinality_df(), 0.05)
    assert st.selectbox_options(chi._GOF_COLUMN) == ["binary", "fifty"]


def test_gof_fifty_categories_remain_eligible(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured = _capture_downloads(monkeypatch)
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _levels_df(50), 0.05)
    summary = captured[chi._STATISTICS_GOF_FILE].iloc[0]
    assert summary["status"] == "ok"
    assert summary["category_count"] == 50
    assert summary["degrees_of_freedom"] == 49


def test_gof_fifty_one_categories_are_refused_with_a_stated_reason() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _levels_df(51), 0.05)
    assert st.selectbox_options(chi._GOF_COLUMN) is None
    assert st.called("info")
    text = st.texts()
    assert "more than 50 distinct levels" in text
    assert "level_00000" not in text


def test_gof_identifier_like_column_is_excluded_with_its_own_reason() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _near_unique_df(60), 0.05)
    assert st.selectbox_options(chi._GOF_COLUMN) is None
    assert "identifier-like" in st.texts()
    assert "id_000000" not in st.texts()


def test_gof_near_unique_column_never_reaches_option_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    real = chi.chi_square_gof_options

    def spy(frame: pd.DataFrame, column: str) -> Any:
        seen.append(column)
        return real(frame, column)

    monkeypatch.setattr(chi, "chi_square_gof_options", spy)
    st = FakeSt(choices={chi._GOF_COLUMN: "identifier"})
    chi.render_chi_square_tests_runner(st, _mixed_cardinality_df(), 0.05)
    assert "identifier" not in seen
    assert "fifty_one" not in seen


def test_gof_caption_is_bounded_for_fifty_categories() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _levels_df(50), 0.05)
    text = st.texts()
    assert "level_00009" in text
    assert "(+40 more)" in text
    assert "level_00010 [str]" not in text


def test_gof_small_category_caption_still_lists_every_label() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _gof_df(), 0.05)
    assert "Observed categories in 'cat': a [str], b [str], c [str]." in st.texts()


def test_gof_custom_proportions_available_at_forty_categories() -> None:
    st = FakeSt(choices={chi._GOF_EXPECTED_MODE: chi._GOF_EXPECTED_CUSTOM})
    chi.render_chi_square_tests_runner(st, _levels_df(40), 0.05)
    assert st.selectbox_options(chi._GOF_EXPECTED_MODE) == list(chi._GOF_EXPECTED_MODES)
    assert len(_prop_widget_keys(st)) == 40


def test_gof_custom_proportions_bounded_above_forty_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    captured = _capture_downloads(monkeypatch)
    st = FakeSt(choices={chi._GOF_EXPECTED_MODE: chi._GOF_EXPECTED_CUSTOM})
    chi.render_chi_square_tests_runner(st, _levels_df(41), 0.05)
    assert _prop_widget_keys(st) == []
    assert st.selectbox_options(chi._GOF_EXPECTED_MODE) == [chi._GOF_EXPECTED_EQUAL]
    assert "Custom expected proportions are available for up to 40 categories" in st.texts()
    summary = captured[chi._STATISTICS_GOF_FILE].iloc[0]
    assert summary["expected_mode"] == "equal"
    assert summary["status"] == "ok"


def test_gof_numbers_are_unchanged_for_an_eligible_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    captured = _capture_downloads(monkeypatch)
    frame = _gof_df()
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, frame, 0.05)
    rendered = captured[chi._STATISTICS_GOF_FILE].iloc[0]
    direct = svc.run_chi_square_gof_test(frame, "cat", alpha=0.05)
    assert rendered["statistic"] == pytest.approx(direct["statistic"])
    assert rendered["p_value"] == pytest.approx(direct["p_value"])
    assert rendered["degrees_of_freedom"] == direct["degrees_of_freedom"]
    assert rendered["reject_null"] == direct["reject_null"]
    assert rendered["alpha"] == direct["alpha"]
    assert list(captured[chi._STATISTICS_GOF_COUNTS_FILE]["observed_count"]) == [30, 30, 40]


# ── F2: bounded result-table rendering (browser preview vs full payload) ──────


def _render_table(
    monkeypatch: pytest.MonkeyPatch, rows: int
) -> tuple[FakeSt, pd.DataFrame, dict[str, pd.DataFrame], dict[str, Any]]:
    frame = pd.DataFrame({"n": list(range(rows)), "label": [f"row_{i}" for i in range(rows)]})
    downloads: dict[str, pd.DataFrame] = {}
    saves: dict[str, Any] = {}
    monkeypatch.setattr(
        chi,
        "csv_download_button",
        lambda st, label, payload, name: downloads.update({name: payload}),
    )
    monkeypatch.setattr(
        chi,
        "render_analysis_csv_save",
        lambda st, **kwargs: saves.update({kwargs["artifact"]: kwargs}),
    )
    st = FakeSt()
    chi._render_downloadable(
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


def _rendered_frame(st: FakeSt) -> pd.DataFrame:
    frames = [a[0] for name, a, _k in st.calls if name == "dataframe"]
    assert len(frames) == 1
    return frames[0]


@pytest.mark.parametrize("rows", [499, 500])
def test_chi_table_below_the_bound_renders_in_full(
    monkeypatch: pytest.MonkeyPatch, rows: int
) -> None:
    st, frame, downloads, saves = _render_table(monkeypatch, rows)
    assert len(_rendered_frame(st)) == rows
    assert len(downloads["table.csv"]) == rows
    assert len(saves["table"]["dataframe"]) == rows
    assert "Showing the first" not in st.texts()
    assert len(frame) == rows


@pytest.mark.parametrize(("rows", "disclosure"), [(501, "500 of 501"), (1_200, "500 of 1,200")])
def test_chi_table_above_the_bound_previews_but_never_truncates_the_payload(
    monkeypatch: pytest.MonkeyPatch, rows: int, disclosure: str
) -> None:
    st, frame, downloads, saves = _render_table(monkeypatch, rows)
    rendered = _rendered_frame(st)
    assert len(rendered) == 500
    assert list(rendered["n"]) == list(range(500))
    assert len(downloads["table.csv"]) == rows
    assert len(saves["table"]["dataframe"]) == rows
    assert f"Showing the first {disclosure} rows." in st.texts()
    assert "Download or save the analysis for the complete table." in st.texts()
    assert len(frame) == rows
    assert list(frame["n"]) == list(range(rows))


def test_chi_contingency_cells_table_uses_the_bounded_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    rows = 240
    frame = pd.DataFrame(
        {
            "x": [f"r_{index % 40:03d}" for index in range(rows)],
            "y": [f"c_{index % 30:03d}" for index in range(rows)],
        }
    )
    downloads: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(
        chi,
        "csv_download_button",
        lambda st, label, payload, name: downloads.update({name: payload}),
    )
    st = FakeSt(choices={chi._CHI_MODE_KEY: chi._CHI_MODE_IND})
    chi.render_chi_square_tests_runner(st, frame, 0.05)
    cells = downloads[chi._STATISTICS_IND_TABLE_FILE]
    assert len(cells) == 40 * 30
    rendered = [a[0] for name, a, _k in st.calls if name == "dataframe"]
    assert all(len(item) <= 500 for item in rendered)
    assert "Showing the first 500 of 1,200 rows." in st.texts()


def test_chi_contingency_captions_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    rows = 240
    frame = pd.DataFrame(
        {
            "x": [f"r_{index % 40:03d}" for index in range(rows)],
            "y": [f"c_{index % 30:03d}" for index in range(rows)],
        }
    )
    st = FakeSt(choices={chi._CHI_MODE_KEY: chi._CHI_MODE_IND})
    chi.render_chi_square_tests_runner(st, frame, 0.05)
    text = st.texts()
    assert "(+30 more)" in text
    assert "(+20 more)" in text
    assert "r_039 [str]" not in text
    assert "c_029 [str]" not in text


def test_chi_contingency_selectors_exclude_unsafe_columns() -> None:
    st = FakeSt(choices={chi._CHI_MODE_KEY: chi._CHI_MODE_IND})
    chi.render_chi_square_tests_runner(st, _mixed_cardinality_df(), 0.05)
    assert st.selectbox_options(chi._IND_FIRST_COLUMN) == ["binary", "fifty"]


def test_chi_homogeneity_selectors_exclude_unsafe_columns() -> None:
    st = FakeSt(choices={chi._CHI_MODE_KEY: chi._CHI_MODE_HOMOG})
    chi.render_chi_square_tests_runner(st, _mixed_cardinality_df(), 0.05)
    assert st.selectbox_options(chi._HOMOG_OUTCOME_COLUMN) == ["binary", "fifty"]


def test_chi_module_has_no_unbounded_category_label_join() -> None:
    source = inspect.getsource(chi)
    assert "', '.join(" not in source
    assert '", ".join(' not in source
