"""Tests for the Statistics Lab paired t-test runner render (page tier).

Reuses the lightweight ``FakeSt`` recorder pattern from
``test_statistics_lab_inferential.py``. The runner routes computation through the
service wrapper (never the domain kernel directly), reports complete-pair and
excluded-row counts, degrades to a structured warning when scipy is absent, and
stays clearly distinct from the existing Wilcoxon signed-rank panel.
"""

from __future__ import annotations

import inspect
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab_runners as runners
from data_quality_toolkit.adapters.ui.pages.statistics_lab import (
    _render_inferential,
    _render_wilcoxon,
)


class FakeSt:
    """Minimal Streamlit recorder supporting columns/selectbox/context use."""

    def __init__(self, checkboxes: dict[str, bool] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
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
        return opts[0] if opts else None

    def checkbox(self, label: str, **k: Any) -> bool:
        self._rec("checkbox", label, **k)
        return bool(self.checkboxes.get(str(k.get("key") or label), False))

    def called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def texts(self) -> str:
        return " ".join(str(x) for _, a, _ in self.calls for x in a if isinstance(x, str))

    def charts(self) -> list[tuple[Any, ...]]:
        return [a for name, a, _k in self.calls if name == "vega_lite_chart"]


def _paired_df(n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    before = rng.normal(10, 2, n)
    after = before + rng.normal(2, 1, n)
    return pd.DataFrame({"before": before, "after": after, "label": ["x"] * n})


def test_renders_parametric_section_and_result_with_scipy() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    runners.render_paired_t_runner(st, _paired_df(), 0.05)
    text = st.texts()
    assert "Paired samples — parametric t-test" in text
    assert "First paired measurement" in text
    assert "Second paired measurement" in text
    assert "Complete pairs" in text
    assert "reject" in text
    assert st.called("dataframe")


def test_download_uses_paired_t_file_name() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    runners.render_paired_t_runner(st, _paired_df(), 0.05)
    downloads = [call for call in st.calls if call[0] == "download_button"]
    assert downloads
    assert downloads[0][2].get("file_name") == "statistics_paired_t.csv"


def test_excluded_rows_reported_when_pairs_incomplete() -> None:
    pytest.importorskip("scipy")
    df = _paired_df()
    df.loc[0, "before"] = np.nan
    df.loc[1, "after"] = np.nan
    st = FakeSt()
    runners.render_paired_t_runner(st, df, 0.05)
    text = st.texts()
    assert "Excluded rows (incomplete pairs)" in text
    assert "Complete pairs" in text


def test_fewer_than_two_numeric_columns_shows_info() -> None:
    st = FakeSt()
    runners.render_paired_t_runner(st, pd.DataFrame({"only": [1.0, 2.0]}), 0.05)
    assert st.called("info")
    assert "two numeric columns" in st.texts()


def test_routes_through_service_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_service(df: pd.DataFrame, column_a: str, column_b: str, **kwargs: Any) -> dict:
        seen.update({"column_a": column_a, "column_b": column_b, **kwargs})
        return {"status": "invalid_input", "reason": "stubbed"}

    monkeypatch.setattr(runners, "run_paired_t_test", fake_service)
    st = FakeSt()
    runners.render_paired_t_runner(st, _paired_df(), 0.05)
    assert seen["column_a"] == "before"
    assert seen["column_b"] == "after"
    assert seen["alpha"] == 0.05
    assert seen["alternative"] == "two-sided"


def test_no_direct_domain_import_in_runner_module() -> None:
    source = inspect.getsource(runners)
    assert "data_quality_toolkit.domain" not in source


def test_scipy_unavailable_renders_structured_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    st = FakeSt()
    runners.render_paired_t_runner(st, _paired_df(), 0.05)  # must not raise
    assert st.called("warning")
    text = st.texts()
    assert "Traceback" not in text


def test_invalid_status_renders_info_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runners,
        "run_paired_t_test",
        lambda *a, **k: {"status": "invalid_input", "reason": "stubbed reason"},
    )
    st = FakeSt()
    runners.render_paired_t_runner(st, _paired_df(), 0.05)
    assert st.called("info")
    assert "stubbed reason" in st.texts()


def test_workspace_save_payload_matches_download(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured: dict[str, Any] = {}

    def fake_download(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
        captured["download"] = df

    def fake_save(st: Any, **kwargs: Any) -> None:
        captured["save"] = kwargs

    monkeypatch.setattr(runners, "csv_download_button", fake_download)
    monkeypatch.setattr(runners, "render_analysis_csv_save", fake_save)
    st = FakeSt()
    runners.render_paired_t_runner(st, _paired_df(), 0.05, dataset_name="demo")
    save = captured["save"]
    assert save["artifact"] == "statistics_paired_t"
    assert save["key"] == "statistics_lab_save_paired_t_btn"
    assert save["dataset_name"] == "demo"
    pd.testing.assert_frame_equal(save["dataframe"], captured["download"])
    row = save["dataframe"].iloc[0]
    assert row["test"] == "PAIRED_T"
    assert row["n_pairs"] == 30


def test_inferential_page_renders_paired_t_and_wilcoxon_separately() -> None:
    pytest.importorskip("scipy")
    # Two-level group column first so the group-comparison selectbox (which picks
    # the first candidate) uses it rather than a high-cardinality numeric column.
    base = _paired_df()
    df = pd.DataFrame(
        {
            "grp": ["x", "y"] * 15,
            "before": base["before"].to_numpy(),
            "after": base["after"].to_numpy(),
        }
    )
    st = FakeSt()
    _render_inferential(st, df, dataset_name=None)
    text = st.texts()
    assert "Paired samples — parametric t-test" in text
    assert "Wilcoxon signed-rank" in text
    # Parametric-vs-nonparametric meaning stays legible on the page.
    assert "nonparametric" in text.lower()


def test_existing_wilcoxon_panel_unchanged_and_distinct() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    _render_wilcoxon(st, _paired_df(), 0.05)
    text = st.texts()
    assert "Wilcoxon signed-rank" in text
    assert "parametric t-test" not in text


# ── opt-in paired evidence ───────────────────────────────────────────────


def test_paired_evidence_is_off_by_default() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    runners.render_paired_t_runner(st, _paired_df(), 0.05)

    assert not st.charts()
    assert runners._PAIRED_T_SHOW_EVIDENCE in [
        k.get("key") for name, _a, k in st.calls if name == "checkbox"
    ]


def test_paired_evidence_renders_before_after_and_difference_views() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({runners._PAIRED_T_SHOW_EVIDENCE: True})

    runners.render_paired_t_runner(st, _paired_df(), 0.05)

    charts = st.charts()
    assert len(charts) == 2
    assert list(charts[0][0].columns) == ["pair", "measurement", "value"]
    assert list(charts[1][0].columns) == ["pair", "before", "after", "difference"]
    # The difference plot carries an explicit zero reference layer.
    assert any(
        layer.get("encoding", {}).get("y", {}).get("datum") == 0 for layer in charts[1][1]["layer"]
    )


def test_paired_evidence_uses_anonymous_positions_and_the_contract_direction() -> None:
    pytest.importorskip("scipy")
    st = FakeSt({runners._PAIRED_T_SHOW_EVIDENCE: True})

    runners.render_paired_t_runner(st, _paired_df(), 0.05)

    data = st.charts()[1][0]
    assert list(data["pair"]) == list(range(1, len(data) + 1))
    assert list(data["difference"]) == pytest.approx(list(data["before"] - data["after"]), abs=1e-5)
    text = st.texts()
    assert "before minus after" in text
    assert "anonymous positions only" in text
    assert "does not establish cause" in text


def test_paired_evidence_bounds_the_displayed_pairs() -> None:
    pytest.importorskip("scipy")
    rows = runners.PAIRED_PLOT_MAX_PAIRS * 3
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {
            "before": rng.normal(10.0, 2.0, rows),
            "after": rng.normal(9.0, 2.0, rows),
        }
    )
    st = FakeSt({runners._PAIRED_T_SHOW_EVIDENCE: True})

    runners.render_paired_t_runner(st, frame, 0.05)

    lines, differences = st.charts()[0][0], st.charts()[1][0]
    assert len(differences) <= runners.PAIRED_PLOT_MAX_PAIRS
    assert len(lines) <= 2 * runners.PAIRED_LINE_DISPLAY_MAX


def test_paired_evidence_adds_no_download_or_workspace_artifact() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    on = FakeSt({runners._PAIRED_T_SHOW_EVIDENCE: True})

    runners.render_paired_t_runner(off, _paired_df(), 0.05)
    runners.render_paired_t_runner(on, _paired_df(), 0.05)

    def names(st: FakeSt) -> list[str]:
        return [
            k["file_name"] for n, _a, k in st.calls if n == "download_button" and "file_name" in k
        ]

    assert names(on) == names(off)
