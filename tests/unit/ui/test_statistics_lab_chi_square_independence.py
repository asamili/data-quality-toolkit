"""Tests for the Statistics Lab chi-square Independence runner render (page tier).

A ``FakeSt`` recorder drives the mode switch and per-key selectbox choices so the
independence contingency runner can be exercised. The runner routes computation through
the service wrapper (never the domain kernel directly), presents type-safe collision-safe
category labels on both axes, states right-tail semantics and the independence
null/alternative question, degrades to a structured warning when scipy is absent, and
renders agreeing summary/table download and workspace-save payloads. The goodness-of-fit
mode and the existing proportion/paired/Wilcoxon panels stay present and distinct.
"""

from __future__ import annotations

import inspect
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab_chi_square as chi
from data_quality_toolkit.adapters.ui.pages.statistics_lab import _render_inferential


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


def _assoc_df(observed: list[list[int]] | None = None) -> pd.DataFrame:
    observed = observed or [[30, 10], [10, 30]]
    rows: list[dict[str, Any]] = []
    for i, row_label in enumerate(["A", "B"]):
        for j, col_label in enumerate(["P", "Q"]):
            rows.extend([{"x": row_label, "y": col_label}] * observed[i][j])
    return pd.DataFrame(rows)


def _ind_st(**kwargs: Any) -> FakeSt:
    choices = {chi._CHI_MODE_KEY: chi._CHI_MODE_IND}
    choices.update(kwargs.get("choices", {}))
    return FakeSt(
        choices=choices,
        numbers=kwargs.get("numbers"),
        checkboxes=kwargs.get("checkboxes"),
    )


def _capture_downloads(monkeypatch: pytest.MonkeyPatch) -> dict[str, pd.DataFrame]:
    captured: dict[str, pd.DataFrame] = {}

    def fake_download(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
        captured[file_name] = df

    monkeypatch.setattr(chi, "csv_download_button", fake_download)
    return captured


# ── mode + wording ────────────────────────────────────────────────────────────


def test_independence_mode_is_offered() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05)
    modes = st.selectbox_options(chi._CHI_MODE_KEY) or []
    assert chi._CHI_MODE_IND in modes


def test_independence_wording_visible() -> None:
    st = _ind_st()
    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05)
    text = st.texts().lower()
    assert "independent" in text
    assert "associated" in text
    assert "right-tail" in text


# ── success + payloads ────────────────────────────────────────────────────────


def test_independence_success_renders_tables() -> None:
    pytest.importorskip("scipy")
    st = _ind_st()
    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05)
    assert st.called("dataframe")
    assert st.called("download_button")


def test_independence_download_payloads_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured = _capture_downloads(monkeypatch)
    st = _ind_st()
    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05, dataset_name="demo")

    summary = captured[chi._STATISTICS_IND_FILE].iloc[0]
    assert summary["test"] == "CHI_IND"
    assert summary["first_column"] == "x"
    assert summary["second_column"] == "y"
    assert summary["degrees_of_freedom"] == 1
    assert summary["valid_rows"] == 80
    assert summary["status"] == "ok"

    table = captured[chi._STATISTICS_IND_TABLE_FILE]
    assert list(table.columns) == [
        "first_category",
        "second_category",
        "observed_count",
        "expected_count",
    ]
    assert len(table) == 4
    cell = table[(table["first_category"] == "A [str]") & (table["second_category"] == "P [str]")]
    assert int(cell["observed_count"].iloc[0]) == 30


def test_independence_workspace_save_matches_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    downloads = _capture_downloads(monkeypatch)
    saves: dict[str, dict[str, Any]] = {}

    def fake_save(st: Any, **kwargs: Any) -> None:
        saves[kwargs["artifact"]] = kwargs

    monkeypatch.setattr(chi, "render_analysis_csv_save", fake_save)
    st = _ind_st()
    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05, dataset_name="demo")

    assert set(saves) == {
        "statistics_chi_square_independence",
        "statistics_chi_square_independence_table",
    }
    pd.testing.assert_frame_equal(
        saves["statistics_chi_square_independence"]["dataframe"],
        downloads[chi._STATISTICS_IND_FILE],
    )
    pd.testing.assert_frame_equal(
        saves["statistics_chi_square_independence_table"]["dataframe"],
        downloads[chi._STATISTICS_IND_TABLE_FILE],
    )


# ── category safety + diagnostics ─────────────────────────────────────────────


def test_independence_colliding_labels_visible_both_axes() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "x": pd.Series([1, "1", 1, "1"], dtype=object),
            "y": pd.Series([1, 1, "1", "1"], dtype=object),
        }
    )
    st = _ind_st()
    chi.render_chi_square_tests_runner(st, df, 0.05)
    text = st.texts()
    assert "1 [int]" in text
    assert "1 [str]" in text


def test_independence_unresolved_collision_renders_warning() -> None:
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
        {"x": pd.Series([Ambiguous("x"), Ambiguous("y")], dtype=object), "y": ["P", "Q"]}
    )
    st = _ind_st()
    chi.render_chi_square_tests_runner(st, df, 0.05)
    # The service is authoritative for category identity; an unresolved-collision
    # rejection surfaces as a structured info callout (no unsafe value leaks).
    assert st.called("info")
    text = st.texts()
    assert "unambiguously" in text
    assert "Traceback" not in text
    assert "0x" not in text


def test_independence_small_cell_warning_surfaced() -> None:
    pytest.importorskip("scipy")
    st = _ind_st()
    chi.render_chi_square_tests_runner(st, _assoc_df([[1, 0], [0, 99]]), 0.05)
    assert "below 1" in st.texts().lower()


def test_independence_scipy_unavailable_structured_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    st = _ind_st()
    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05)  # must not raise
    assert st.called("warning")
    assert "Traceback" not in st.texts()


# ── mode isolation + integration ──────────────────────────────────────────────


def test_gof_mode_still_dispatches_separately() -> None:
    gof = FakeSt(choices={chi._CHI_MODE_KEY: chi._CHI_MODE_GOF})
    chi.render_chi_square_tests_runner(gof, _assoc_df(), 0.05)
    assert gof.selectbox_options(chi._GOF_COLUMN) is not None
    assert gof.selectbox_options(chi._IND_FIRST_COLUMN) is None

    ind = _ind_st()
    chi.render_chi_square_tests_runner(ind, _assoc_df(), 0.05)
    assert ind.selectbox_options(chi._IND_FIRST_COLUMN) is not None
    assert ind.selectbox_options(chi._GOF_COLUMN) is None


def test_no_direct_domain_import_in_chi_module() -> None:
    assert "data_quality_toolkit.domain" not in inspect.getsource(chi)


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
    assert text.count("Chi-square tests") == 1
    assert "Proportion tests" in text
    assert "Paired samples — parametric t-test" in text


# ── opt-in independence evidence (owner contract) ─────────────────────────


def test_independence_evidence_is_off_by_default_and_owned_by_this_module() -> None:
    pytest.importorskip("scipy")
    st = _ind_st()

    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05)

    assert not st.charts()
    assert chi._IND_SHOW_EVIDENCE in [
        k.get("key") for name, _a, k in st.calls if name == "checkbox"
    ]


def test_independence_evidence_renders_a_signed_residual_heatmap() -> None:
    pytest.importorskip("scipy")
    st = _ind_st(checkboxes={chi._IND_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05)

    data, spec = st.charts()[0]
    assert spec["mark"]["type"] == "rect"
    assert spec["encoding"]["color"]["field"] == "residual"
    assert list(data["row_category"]) == ["A [str]", "A [str]", "B [str]", "B [str]"]
    assert list(data["col_category"]) == ["P [str]", "Q [str]", "P [str]", "Q [str]"]
    assert list(data["observed"]) == [30, 10, 10, 30]
    assert list(data["expected"]) == pytest.approx([20.0, 20.0, 20.0, 20.0])
    assert list(data["residual"]) == pytest.approx(
        [10 / 20**0.5, -(10 / 20**0.5), -(10 / 20**0.5), 10 / 20**0.5], rel=1e-5
    )


def test_independence_evidence_ranks_the_largest_departures() -> None:
    pytest.importorskip("scipy")
    st = _ind_st(checkboxes={chi._IND_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _assoc_df([[40, 5], [5, 40]]), 0.05)

    ranked = [
        args[0]
        for name, args, _k in st.calls
        if name == "dataframe" and "direction" in getattr(args[0], "columns", [])
    ]
    assert ranked
    assert set(ranked[0]["direction"]) <= {"observed above expected", "observed below expected"}
    text = st.texts()
    assert "Cells ranked by the size of their departure" in text
    assert "positive Pearson residual" in text


def test_independence_evidence_carries_the_no_causation_caveat_and_guidance() -> None:
    pytest.importorskip("scipy")
    st = _ind_st(checkboxes={chi._IND_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05)

    text = st.texts()
    assert "does not establish cause" in text
    assert "no post-hoc comparison" in text
    assert "What this does not show" in text


def test_independence_evidence_reports_sparse_expected_counts_informationally() -> None:
    pytest.importorskip("scipy")
    st = _ind_st(checkboxes={chi._IND_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _assoc_df([[1, 0], [0, 99]]), 0.05)

    text = st.texts()
    assert "expected count below 5" in text
    assert "does not change the test that ran" in text


def test_independence_evidence_does_not_rerun_the_test(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    calls: list[int] = []
    original = chi.run_chi_square_independence_test

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(chi, "run_chi_square_independence_test", counting)
    st = _ind_st(checkboxes={chi._IND_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _assoc_df(), 0.05)

    assert len(calls) == 1
