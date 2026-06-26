"""Focused contracts for the bounded Drift Explorer UX redesign."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.pages import drift_explorer as page
from data_quality_toolkit.adapters.ui.services import monitoring as svc
from data_quality_toolkit.application.monitoring.view_model import (
    ColumnDrift,
    DistributionBin,
    MonitoringOverview,
    RunDetail,
    RunRow,
    TrendSummary,
)


class FakeSt:
    """Small Streamlit recorder with configurable widget values."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.number_values: dict[str, int | float] = {}
        self.select_values: dict[str, Any] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def __getattr__(self, name: str) -> Any:
        def recorder(*args: Any, **kwargs: Any) -> None:
            self._record(name, *args, **kwargs)

        return recorder

    def columns(self, count: int) -> list[FakeSt]:
        return [self for _ in range(count)]

    def expander(self, label: str, **kwargs: Any) -> FakeSt:
        self._record("expander", label, **kwargs)
        return self

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        return self.text_values.get(label, str(kwargs.get("value", "")))

    def number_input(self, label: str, **kwargs: Any) -> int | float:
        self._record("number_input", label, **kwargs)
        value = self.number_values.get(label, kwargs.get("value", kwargs.get("min_value", 0)))
        if isinstance(value, int | float):
            return value
        raise TypeError(f"Non-numeric test widget value for {label!r}")

    def selectbox(self, label: str, options: Sequence[Any] = (), **kwargs: Any) -> Any:
        self._record("selectbox", label, options, **kwargs)
        return self.select_values.get(label, options[0] if options else None)

    def calls_named(self, name: str) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
        return [call for call in self.calls if call[0] == name]

    def rendered_text(self) -> str:
        return " ".join(
            str(value) for _, args, _ in self.calls for value in args if isinstance(value, str)
        )


def _run(run_id: str = "run-2", *, drift: bool | None = True, alpha: float | None = 0.05) -> RunRow:
    return RunRow(
        run_id=run_id,
        created_at="2026-06-20T10:00:00+00:00",
        current_dataset_id="dataset-1",
        status="ok",
        drift_detected=drift,
        columns_tested=3,
        columns_drifted=1 if drift else 0,
        columns_skipped=0,
        alpha=alpha,
    )


def _overview(runs: list[RunRow]) -> MonitoringOverview:
    latest = runs[0] if runs else None
    drifted = sum(run.drift_detected is True for run in runs)
    return MonitoringOverview(
        summary=TrendSummary(
            total_runs=len(runs),
            drifted_runs=drifted,
            non_drifted_runs=sum(run.drift_detected is False for run in runs),
            drift_rate=drifted / len(runs) if runs else 0.0,
            latest_run_id=latest.run_id if latest else None,
            latest_created_at=latest.created_at if latest else None,
            latest_drift_detected=latest.drift_detected if latest else None,
            columns_tested_total=sum(run.columns_tested or 0 for run in runs),
            columns_tested_average=3.0 if runs else 0.0,
            columns_drifted_total=sum(run.columns_drifted or 0 for run in runs),
            columns_drifted_average=0.5 if runs else 0.0,
        ),
        runs=runs,
        db_path="C:/private/user/monitoring.db",
        current_dataset_id=None,
        limit=100,
        generated_at="2026-06-20T10:01:00+00:00",
    )


def _column(*, psi: float | None = 0.3) -> ColumnDrift:
    return ColumnDrift(
        column_name="synthetic_measure",
        kind="numeric",
        test="ks",
        drift_detected=True,
        statistic=0.4,
        p_value=0.01,
        psi=psi,
        js_distance=0.2,
        wasserstein=1.2,
        reference_n=100,
        current_n=120,
        status="ok",
        skip_reason=None,
    )


def test_empty_db_path_state_does_not_load(monkeypatch: pytest.MonkeyPatch) -> None:
    st = FakeSt()
    called = False

    def fail_if_called(*_: Any, **__: Any) -> Any:
        nonlocal called
        called = True

    monkeypatch.setattr(page, "load_monitoring_overview", fail_if_called)
    page._render_drift_explorer(st)

    assert called is False
    assert "Enter a local SQLite monitoring database path" in st.rendered_text()


def test_missing_path_state_uses_basename_only() -> None:
    st = FakeSt()
    private_path = "C:/private/user/does-not-exist.db"
    st.text_values["Local monitoring database"] = private_path
    page._render_drift_explorer(st)

    text = st.rendered_text()
    assert "does-not-exist.db" in text
    assert "C:/private/user" not in text


def test_no_history_state(monkeypatch: pytest.MonkeyPatch) -> None:
    st = FakeSt()
    st.text_values["Local monitoring database"] = "monitoring.db"
    monkeypatch.setattr(page, "load_monitoring_overview", lambda *a, **k: (_overview([]), None))

    page._render_drift_explorer(st)

    assert "No monitoring runs were found" in st.rendered_text()


def test_one_run_has_insufficient_trend_but_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    overview = _overview([_run()])
    st = FakeSt()
    st.text_values["Local monitoring database"] = "monitoring.db"
    detail_calls: list[str] = []
    monkeypatch.setattr(page, "load_monitoring_overview", lambda *a, **k: (overview, None))
    monkeypatch.setattr(
        page, "_render_columns_section", lambda _st, _db, run_id: detail_calls.append(run_id)
    )

    page._render_drift_explorer(st)

    assert "Insufficient trend history" in st.rendered_text()
    assert not st.calls_named("line_chart")
    assert detail_calls == ["run-2"]


def test_multiple_runs_render_history_series(monkeypatch: pytest.MonkeyPatch) -> None:
    overview = _overview([_run(), _run("run-1", drift=False)])
    st = FakeSt()
    st.text_values["Local monitoring database"] = "monitoring.db"
    monkeypatch.setattr(page, "load_monitoring_overview", lambda *a, **k: (overview, None))
    monkeypatch.setattr(page, "_render_columns_section", lambda *a, **k: None)

    page._render_drift_explorer(st)

    assert st.calls_named("line_chart")
    assert "Oldest to newest" in st.rendered_text()


def test_dataset_filter_and_limit_are_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    st = FakeSt()
    st.text_values["Local monitoring database"] = "monitoring.db"
    st.text_values["Current dataset ID filter"] = "dataset-exact-value"
    st.number_values["Maximum monitoring runs"] = 17
    captured: dict[str, Any] = {}

    def load(*args: Any, **kwargs: Any) -> tuple[MonitoringOverview, None]:
        captured["args"] = args
        captured.update(kwargs)
        return _overview([]), None

    monkeypatch.setattr(page, "load_monitoring_overview", load)
    page._render_drift_explorer(st)

    assert captured["current_dataset_id"] == "dataset-exact-value"
    assert captured["limit"] == 17
    assert any(call[1][0] == "Current dataset ID filter" for call in st.calls_named("text_input"))


def test_no_dataset_filter_warns_about_mixed_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    st = FakeSt()
    st.text_values["Local monitoring database"] = "monitoring.db"
    monkeypatch.setattr(page, "load_monitoring_overview", lambda *a, **k: (_overview([]), None))

    page._render_drift_explorer(st)

    assert "multiple current_dataset_id values" in st.rendered_text()


@pytest.mark.parametrize(("value", "label"), [(True, "Yes"), (False, "No"), (None, "Unknown")])
def test_latest_drift_state_preserves_tristate(value: bool | None, label: str) -> None:
    assert svc.format_drift_state(value) == label


@pytest.mark.parametrize(("alpha", "expected"), [(0.05, "0.0500"), (None, "unavailable")])
def test_run_detail_alpha_visible(
    alpha: float | None, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    st = FakeSt()
    detail = RunDetail(run=_run(alpha=alpha), columns=[], distributions=[])
    monkeypatch.setattr(page, "load_run_detail", lambda *a, **k: (detail, None))

    page._render_columns_section(st, "monitoring.db", "run-2")

    alpha_calls = [call for call in st.calls_named("metric") if call[1][0] == "Alpha"]
    assert alpha_calls[0][1][1] == expected


def test_drift_rate_threshold_equality_is_not_breach_and_greater_is() -> None:
    overview = _overview([_run(), _run("run-1", drift=False)])
    equal = svc.evaluate_drift_rate_for_display(overview, threshold=0.5)
    above = svc.evaluate_drift_rate_for_display(overview, threshold=0.49)
    assert equal["breached"] is False
    assert above["breached"] is True


def test_psi_control_requires_authoritative_values() -> None:
    no_psi = FakeSt()
    page._render_psi_threshold(no_psi, [_column(psi=None)])
    assert not no_psi.calls_named("number_input")
    assert "no recorded PSI values" in no_psi.rendered_text()

    with_psi = FakeSt()
    page._render_psi_threshold(with_psi, [_column(psi=0.3)])
    assert with_psi.calls_named("number_input")[0][1][0] == "Maximum acceptable PSI"
    assert "PSI threshold breached" in with_psi.rendered_text()


def test_missing_distribution_probabilities_stay_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    st = FakeSt()
    bins = [
        DistributionBin(
            column_name="synthetic_measure",
            kind="numeric",
            bin_index=0,
            bin_label="synthetic-bin",
            reference_prob=None,
            current_prob=0.25,
        )
    ]
    monkeypatch.setattr(page, "load_distribution_series", lambda *a, **k: (bins, None))

    page._render_distribution_section(st, "monitoring.db", "run-2", ["synthetic_measure"])

    table_rows = st.calls_named("dataframe")[0][1][0]
    chart_rows = st.calls_named("bar_chart")[0][1][0]
    assert table_rows[0]["Reference probability"] == "unavailable"
    assert chart_rows[0]["Reference"] == 0.0
    assert "zero-filled solely so Streamlit can draw" in st.rendered_text()


def test_storylens_is_bounded_and_excludes_db_path() -> None:
    overview = _overview([_run(), _run("run-1", drift=False)])
    cards = svc.build_drift_storylens_cards(
        overview, threshold_metric="drift_rate", threshold_value=0.2
    )
    blob = " ".join(
        [
            card.title
            + card.summary
            + " ".join(card.evidence)
            + card.recommended_action
            + card.limitations
            for card in cards
        ]
    )
    assert len(cards) <= 2
    assert overview.db_path not in blob
    assert "C:/private/user" not in blob
