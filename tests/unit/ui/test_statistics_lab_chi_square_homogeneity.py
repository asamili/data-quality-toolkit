"""Tests for the Statistics Lab chi-square Homogeneity runner render (page tier).

A ``FakeSt`` recorder drives the mode switch and per-key selectbox choices so the
homogeneity contingency runner can be exercised. The runner reuses the shared
contingency preparation (populations on the rows, outcome categories on the columns),
uses distinct homogeneity wording (no causal or post-hoc claim), routes through the
distinct ``CHI_HOMOG`` public key (never ``CHI_IND``), degrades to a structured warning
when scipy is absent, and renders agreeing summary/table download and workspace-save
payloads. The goodness-of-fit and independence modes stay present and distinct.
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


def _homog_df(observed: list[list[int]] | None = None) -> pd.DataFrame:
    """Two populations (G1, G2) × two outcomes (yes, no); response column comes first."""
    observed = observed or [[30, 10], [10, 30]]
    rows: list[dict[str, Any]] = []
    for gi, group in enumerate(["G1", "G2"]):
        for oj, outcome in enumerate(["yes", "no"]):
            rows.extend([{"response": outcome, "population": group}] * observed[gi][oj])
    return pd.DataFrame(rows)


def _homog_st(**kwargs: Any) -> FakeSt:
    choices = {chi._CHI_MODE_KEY: chi._CHI_MODE_HOMOG}
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


def test_homogeneity_mode_is_offered() -> None:
    st = FakeSt()
    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)
    modes = st.selectbox_options(chi._CHI_MODE_KEY) or []
    assert chi._CHI_MODE_HOMOG in modes


def test_homogeneity_distinct_wording_no_causation_or_post_hoc() -> None:
    st = _homog_st()
    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)
    text = st.texts().lower()
    assert "same outcome distribution" in text
    assert "at least one" in text
    assert "causation" in text
    assert "post-hoc" in text
    assert "right-tail" in text
    # Distinct from the independence framing.
    assert "associated" not in text


# ── success + payloads ────────────────────────────────────────────────────────


def test_homogeneity_success_renders_tables() -> None:
    pytest.importorskip("scipy")
    st = _homog_st()
    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)
    assert st.called("dataframe")
    assert st.called("download_button")


def test_homogeneity_download_payloads_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured = _capture_downloads(monkeypatch)
    st = _homog_st()
    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05, dataset_name="demo")

    summary = captured[chi._STATISTICS_HOMOG_FILE].iloc[0]
    assert summary["test"] == "CHI_HOMOG"
    assert summary["group_column"] == "population"
    assert summary["outcome_column"] == "response"
    assert summary["degrees_of_freedom"] == 1
    assert summary["valid_rows"] == 80
    assert summary["status"] == "ok"

    table = captured[chi._STATISTICS_HOMOG_TABLE_FILE]
    assert list(table.columns) == ["group", "outcome", "observed_count", "expected_count"]
    assert len(table) == 4
    # Populations on the group axis, outcomes on the outcome axis.
    assert set(table["group"]) == {"G1 [str]", "G2 [str]"}
    assert set(table["outcome"]) == {"yes [str]", "no [str]"}


def test_homogeneity_workspace_save_matches_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    downloads = _capture_downloads(monkeypatch)
    saves: dict[str, dict[str, Any]] = {}

    def fake_save(st: Any, **kwargs: Any) -> None:
        saves[kwargs["artifact"]] = kwargs

    monkeypatch.setattr(chi, "render_analysis_csv_save", fake_save)
    st = _homog_st()
    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05, dataset_name="demo")

    assert set(saves) == {
        "statistics_chi_square_homogeneity",
        "statistics_chi_square_homogeneity_table",
    }
    pd.testing.assert_frame_equal(
        saves["statistics_chi_square_homogeneity"]["dataframe"],
        downloads[chi._STATISTICS_HOMOG_FILE],
    )
    pd.testing.assert_frame_equal(
        saves["statistics_chi_square_homogeneity_table"]["dataframe"],
        downloads[chi._STATISTICS_HOMOG_TABLE_FILE],
    )


# ── safety + degradation ──────────────────────────────────────────────────────


def test_homogeneity_scipy_unavailable_structured_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    st = _homog_st()
    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)  # must not raise
    assert st.called("warning")
    assert "Traceback" not in st.texts()


def test_homogeneity_unresolved_collision_renders_info() -> None:
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
            "response": ["yes", "no"],
            "population": pd.Series([Ambiguous("x"), Ambiguous("y")], dtype=object),
        }
    )
    st = _homog_st()
    chi.render_chi_square_tests_runner(st, df, 0.05)
    assert st.called("info")
    assert "unambiguously" in st.texts()
    assert "0x" not in st.texts()


# ── mode isolation + integration ──────────────────────────────────────────────


def test_three_modes_dispatch_separately() -> None:
    gof = FakeSt(choices={chi._CHI_MODE_KEY: chi._CHI_MODE_GOF})
    chi.render_chi_square_tests_runner(gof, _homog_df(), 0.05)
    assert gof.selectbox_options(chi._GOF_COLUMN) is not None
    assert gof.selectbox_options(chi._HOMOG_OUTCOME_COLUMN) is None

    ind = FakeSt(choices={chi._CHI_MODE_KEY: chi._CHI_MODE_IND})
    chi.render_chi_square_tests_runner(ind, _homog_df(), 0.05)
    assert ind.selectbox_options(chi._IND_FIRST_COLUMN) is not None
    assert ind.selectbox_options(chi._HOMOG_OUTCOME_COLUMN) is None

    homog = _homog_st()
    chi.render_chi_square_tests_runner(homog, _homog_df(), 0.05)
    assert homog.selectbox_options(chi._HOMOG_OUTCOME_COLUMN) is not None
    assert homog.selectbox_options(chi._GOF_COLUMN) is None
    assert homog.selectbox_options(chi._IND_FIRST_COLUMN) is None


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
    assert "Wilcoxon signed-rank" in text


# ── opt-in homogeneity evidence (owner contract) ──────────────────────────


def test_homogeneity_evidence_is_off_by_default_with_its_own_toggle() -> None:
    pytest.importorskip("scipy")
    st = _homog_st()

    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)

    assert not st.charts()
    keys = [k.get("key") for name, _a, k in st.calls if name == "checkbox"]
    assert chi._HOMOG_SHOW_EVIDENCE in keys
    assert chi._IND_SHOW_EVIDENCE not in keys


def test_homogeneity_evidence_orients_groups_on_rows_and_outcomes_on_columns() -> None:
    pytest.importorskip("scipy")
    st = _homog_st(checkboxes={chi._HOMOG_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)

    data, spec = st.charts()[0]
    assert spec["encoding"]["y"]["title"] == "group"
    assert spec["encoding"]["x"]["title"] == "outcome"
    # Axes keep the service's deterministic label order (rows = populations,
    # columns = outcome categories sorted by their collision-safe label).
    assert list(data["row_category"]) == ["G1 [str]", "G1 [str]", "G2 [str]", "G2 [str]"]
    assert list(data["col_category"]) == ["no [str]", "yes [str]", "no [str]", "yes [str]"]
    assert list(data["observed"]) == [10, 30, 30, 10]


def test_homogeneity_evidence_keeps_its_distinct_framing_and_caveats() -> None:
    pytest.importorskip("scipy")
    st = _homog_st(checkboxes={chi._HOMOG_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)

    text = st.texts().lower()
    assert "same outcome distribution" in text
    assert "which group differs" in text
    assert "does not establish cause" in text
    assert "no post-hoc comparison" in text


def test_homogeneity_evidence_does_not_rerun_the_test(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    calls: list[int] = []
    original = chi.run_chi_square_homogeneity_test

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(chi, "run_chi_square_homogeneity_test", counting)
    st = _homog_st(checkboxes={chi._HOMOG_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)

    assert len(calls) == 1


def test_homogeneity_evidence_adds_no_download_or_workspace_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    saves: list[str] = []
    monkeypatch.setattr(
        chi, "render_analysis_csv_save", lambda _st, **kwargs: saves.append(kwargs["artifact"])
    )
    downloads = _capture_downloads(monkeypatch)
    st = _homog_st(checkboxes={chi._HOMOG_SHOW_EVIDENCE: True})

    chi.render_chi_square_tests_runner(st, _homog_df(), 0.05)

    assert saves == [
        "statistics_chi_square_homogeneity",
        "statistics_chi_square_homogeneity_table",
    ]
    assert set(downloads) == {chi._STATISTICS_HOMOG_FILE, chi._STATISTICS_HOMOG_TABLE_FILE}
