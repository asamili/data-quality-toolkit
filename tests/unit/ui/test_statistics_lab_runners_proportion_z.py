"""Tests for the Statistics Lab proportion z-test runners render (page tier).

An extended ``FakeSt`` recorder drives per-key selectbox/number_input choices so both
proportion modes and specific typed category selections can be exercised. The runners
route computation through the service wrappers (never the domain kernel directly),
present type-safe category options with disambiguated labels (``1 [int]`` vs
``1 [str]``), state binary-outcome guidance and one-sided direction meaning, degrade
to a structured warning when scipy is absent, and render agreeing download/save
payloads. The existing PAIRED_T and Wilcoxon panels stay present and distinct.
"""

from __future__ import annotations

import inspect
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import statistics_lab_runners as runners
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


def _binary_df(successes: int = 70, failures: int = 30) -> pd.DataFrame:
    return pd.DataFrame({"outcome": ["yes"] * successes + ["no"] * failures})


def _two_group_df() -> pd.DataFrame:
    outcome = ["yes"] * 20 + ["no"] * 10 + ["yes"] * 10 + ["no"] * 30
    group = ["A"] * 30 + ["B"] * 40
    return pd.DataFrame({"outcome": outcome, "grp": group})


def _outcome_options(df: pd.DataFrame, column: str) -> list[Any]:
    options, error = svc.outcome_category_options(df, column)
    assert error is None
    return options


def _group_options(df: pd.DataFrame, column: str) -> list[Any]:
    options, error = svc.group_category_options(df, column)
    assert error is None
    return options


def _option(options: list[Any], value: Any) -> Any:
    return next(option for option in options if option.value == value)


def _labels(options: list[Any] | None) -> list[str]:
    assert options is not None
    return [option.label for option in options]


def _values(options: list[Any] | None) -> list[Any]:
    assert options is not None
    return [option.value for option in options]


# ── section + mode switch ─────────────────────────────────────────────────────


def test_section_renders_with_binary_guidance() -> None:
    st = FakeSt()
    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)
    text = st.texts()
    assert "Proportion tests" in text
    assert "binary" in text.lower()


def test_two_modes_are_distinct() -> None:
    st = FakeSt()
    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)
    assert st.selectbox_options(runners._PROP_MODE_KEY) == list(runners._PROP_MODES)


def test_one_and_two_proportion_modes_dispatch_separately() -> None:
    one = FakeSt(choices={runners._PROP_MODE_KEY: runners._PROP_MODE_ONE})
    runners.render_proportion_tests_runner(one, _two_group_df(), 0.05)
    assert one.selectbox_options(runners._ONE_PROP_OUTCOME) is not None
    assert one.selectbox_options(runners._TWO_PROP_GROUP_COLUMN) is None

    two = FakeSt(choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO})
    runners.render_proportion_tests_runner(two, _two_group_df(), 0.05)
    assert two.selectbox_options(runners._TWO_PROP_GROUP_COLUMN) is not None
    assert two.selectbox_options(runners._ONE_PROP_OUTCOME) is None


# ── one-proportion runner ─────────────────────────────────────────────────────


def test_one_prop_success_options_are_typed_categories() -> None:
    st = FakeSt()
    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)
    assert _labels(st.selectbox_options(runners._ONE_PROP_SUCCESS)) == ["no [str]", "yes [str]"]


def test_one_prop_direction_wording_visible() -> None:
    st = FakeSt()
    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)
    text = st.texts()
    assert "greater" in text
    assert "less" in text
    assert "null proportion" in text.lower()


def test_one_prop_multi_category_rejected_actionably() -> None:
    df = pd.DataFrame({"outcome": ["a", "b", "c", "a"]})
    st = FakeSt()
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert st.called("info")
    assert "exactly two distinct" in st.texts()


def test_one_prop_colliding_labels_are_visibly_distinct() -> None:
    df = pd.DataFrame({"outcome": pd.Series([1, "1", 1, "1"], dtype=object)})
    st = FakeSt()
    runners.render_proportion_tests_runner(st, df, 0.05)
    labels = _labels(st.selectbox_options(runners._ONE_PROP_SUCCESS))
    assert labels == ["1 [int]", "1 [str]"]
    assert "1 [int]" in st.texts() and "1 [str]" in st.texts()


def test_one_prop_selected_label_maps_to_native_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame({"outcome": pd.Series([1, "1", 1, "1"], dtype=object)})
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        runners, "csv_download_button", lambda st, label, frame, name: captured.update(df=frame)
    )
    int_option = _option(_outcome_options(df, "outcome"), 1)
    st = FakeSt(choices={runners._ONE_PROP_SUCCESS: int_option})
    runners.render_proportion_tests_runner(st, df, 0.05)
    row = captured["df"].iloc[0]
    assert row["success_value"] == "1 [int]"
    assert row["success_count"] == 2  # only the two int rows, not the str rows


def test_one_prop_successful_result_renders_table() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()
    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)
    assert st.called("dataframe")
    assert st.called("download_button")


def test_one_prop_invalid_status_renders_info() -> None:
    st = FakeSt(numbers={runners._ONE_PROP_NULL: 1.5})
    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)
    assert st.called("info")
    assert "null proportion" in st.texts().lower()


def test_one_prop_download_payload_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured: dict[str, Any] = {}

    def fake_download(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
        captured["df"] = df
        captured["file_name"] = file_name

    monkeypatch.setattr(runners, "csv_download_button", fake_download)
    df = _binary_df()
    yes_option = _option(_outcome_options(df, "outcome"), "yes")
    st = FakeSt(choices={runners._ONE_PROP_SUCCESS: yes_option})
    runners.render_proportion_tests_runner(st, df, 0.05, dataset_name="demo")
    assert captured["file_name"] == "statistics_one_proportion_z.csv"
    row = captured["df"].iloc[0]
    assert row["test"] == "ONE_PROP_Z"
    assert row["success_value"] == "yes [str]"
    assert row["success_count"] == 70
    assert row["valid_rows"] == 100
    assert row["status"] == "ok"


def test_one_prop_workspace_save_matches_download(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured: dict[str, Any] = {}

    def fake_download(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
        captured["download"] = df

    def fake_save(st: Any, **kwargs: Any) -> None:
        captured["save"] = kwargs

    monkeypatch.setattr(runners, "csv_download_button", fake_download)
    monkeypatch.setattr(runners, "render_analysis_csv_save", fake_save)
    df = _binary_df()
    yes_option = _option(_outcome_options(df, "outcome"), "yes")
    st = FakeSt(choices={runners._ONE_PROP_SUCCESS: yes_option})
    runners.render_proportion_tests_runner(st, df, 0.05, dataset_name="demo")
    save = captured["save"]
    assert save["artifact"] == "statistics_one_proportion_z"
    assert save["dataset_name"] == "demo"
    pd.testing.assert_frame_equal(save["dataframe"], captured["download"])


def test_one_prop_scipy_unavailable_structured_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from data_quality_toolkit.domain.statistics import inference

    monkeypatch.setattr(inference, "import_scipy_stats", lambda: None)
    st = FakeSt()
    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)  # must not raise
    assert st.called("warning")
    assert "Traceback" not in st.texts()
    assert "object at 0x" not in st.texts()


# ── two-proportion runner ─────────────────────────────────────────────────────


def _two_prop_st(df: pd.DataFrame, success: Any, group_a: Any, group_b: Any) -> FakeSt:
    return FakeSt(
        choices={
            runners._PROP_MODE_KEY: runners._PROP_MODE_TWO,
            runners._TWO_PROP_SUCCESS: _option(_outcome_options(df, "outcome"), success),
            runners._TWO_PROP_GROUP_A: _option(_group_options(df, "grp"), group_a),
            runners._TWO_PROP_GROUP_B: _option(_group_options(df, "grp"), group_b),
        }
    )


def test_two_prop_direction_first_minus_second_visible() -> None:
    df = _two_group_df()
    st = _two_prop_st(df, "yes", "A", "B")
    runners.render_proportion_tests_runner(st, df, 0.05)
    text = st.texts()
    assert "first selected group minus the second" in text
    assert "first minus second" in text
    assert "greater" in text and "less" in text


def test_two_prop_successful_result_renders_table() -> None:
    pytest.importorskip("scipy")
    df = _two_group_df()
    st = _two_prop_st(df, "yes", "A", "B")
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert st.called("dataframe")
    assert st.called("download_button")


def test_two_prop_download_payload_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured: dict[str, Any] = {}

    def fake_download(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
        captured["df"] = df
        captured["file_name"] = file_name

    monkeypatch.setattr(runners, "csv_download_button", fake_download)
    df = _two_group_df()
    st = _two_prop_st(df, "yes", "A", "B")
    runners.render_proportion_tests_runner(st, df, 0.05, dataset_name="demo")
    assert captured["file_name"] == "statistics_two_proportion_z.csv"
    row = captured["df"].iloc[0]
    assert row["test"] == "TWO_PROP_Z"
    assert row["success_value"] == "yes [str]"
    assert row["first_group"] == "A [str]"
    assert row["second_group"] == "B [str]"
    assert row["n_first_group"] == 30
    assert row["n_second_group"] == 40
    assert row["successes_first_group"] == 20
    assert row["successes_second_group"] == 10
    assert row["proportion_difference"] == pytest.approx(20 / 30 - 0.25)


def test_two_prop_workspace_save_matches_download(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("scipy")
    captured: dict[str, Any] = {}

    def fake_download(st: Any, label: str, df: pd.DataFrame, file_name: str) -> None:
        captured["download"] = df

    def fake_save(st: Any, **kwargs: Any) -> None:
        captured["save"] = kwargs

    monkeypatch.setattr(runners, "csv_download_button", fake_download)
    monkeypatch.setattr(runners, "render_analysis_csv_save", fake_save)
    df = _two_group_df()
    st = _two_prop_st(df, "yes", "A", "B")
    runners.render_proportion_tests_runner(st, df, 0.05, dataset_name="demo")
    save = captured["save"]
    assert save["artifact"] == "statistics_two_proportion_z"
    pd.testing.assert_frame_equal(save["dataframe"], captured["download"])


def test_two_prop_colliding_group_labels_are_distinct() -> None:
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", "no", "yes"],
            "grp": pd.Series([1, 1, "1", "1", 2], dtype=object),
        }
    )
    st = FakeSt(choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO})
    runners.render_proportion_tests_runner(st, df, 0.05)
    labels = _labels(st.selectbox_options(runners._TWO_PROP_GROUP_A))
    assert "1 [int]" in labels
    assert "1 [str]" in labels


def test_two_prop_non_finite_groups_not_selectable() -> None:
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", "no"],
            "grp": [1.0, 2.0, np.inf, -np.inf],
        }
    )
    st = FakeSt(choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO})
    runners.render_proportion_tests_runner(st, df, 0.05)
    values = _values(st.selectbox_options(runners._TWO_PROP_GROUP_A))
    assert set(values) == {1.0, 2.0}
    assert all(np.isfinite(v) for v in values)


def test_two_prop_insufficient_group_renders_info() -> None:
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", np.nan, np.nan],
            "grp": ["A", "A", "B", "D", "D"],
        }
    )
    st = _two_prop_st(df, "yes", "A", "D")
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert st.called("info")
    assert "no valid observations" in st.texts()


# ── R2 display-collision safety (page tier) ───────────────────────────────────


def _status_class(module_name: str) -> type:
    class Status:
        def __init__(self, text: str) -> None:
            self._text = text

        def __str__(self) -> str:
            return self._text

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Status) and self._text == other._text

        def __hash__(self) -> int:
            return hash((module_name, self._text))

    Status.__module__ = module_name
    return Status


def _ambiguous_class() -> type:
    class Ambiguous:
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def __str__(self) -> str:
            return "same"

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Ambiguous) and self.tag == other.tag

        def __hash__(self) -> int:
            return hash(("ambiguous", self.tag))

    return Ambiguous


def test_one_prop_different_module_labels_visibly_distinct() -> None:
    status_a = _status_class("pkg_a.statuses")
    status_b = _status_class("pkg_b.statuses")
    df = pd.DataFrame(
        {"outcome": pd.Series([status_a("Open"), status_a("Open"), status_b("Open")], dtype=object)}
    )
    st = FakeSt()
    runners.render_proportion_tests_runner(st, df, 0.05)
    labels = _labels(st.selectbox_options(runners._ONE_PROP_SUCCESS))
    assert labels[0] != labels[1]
    joined = " ".join(labels)
    assert "pkg_a.statuses" in joined and "pkg_b.statuses" in joined


def test_one_prop_unresolved_collision_renders_warning_no_selectbox() -> None:
    ambiguous = _ambiguous_class()
    df = pd.DataFrame({"outcome": pd.Series([ambiguous("x"), ambiguous("y")], dtype=object)})
    st = FakeSt()
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert st.called("warning")
    # No success selectbox is rendered for an ambiguous category set.
    assert st.selectbox_options(runners._ONE_PROP_SUCCESS) is None
    text = st.texts()
    assert "Traceback" not in text
    assert "0x" not in text


def test_one_prop_opaque_object_renders_warning_without_address() -> None:
    df = pd.DataFrame({"outcome": pd.Series([object(), "ok"], dtype=object)})
    st = FakeSt()
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert st.called("warning")
    assert st.selectbox_options(runners._ONE_PROP_SUCCESS) is None
    text = st.texts()
    assert "0x" not in text
    assert "object at" not in text.lower()


def test_one_prop_control_character_renders_warning() -> None:
    df = pd.DataFrame({"outcome": pd.Series(["line\nbreak", "ok"], dtype=object)})
    st = FakeSt()
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert st.called("warning")
    assert st.selectbox_options(runners._ONE_PROP_SUCCESS) is None
    # No raw newline leaks into a broken multiline label.
    assert "line\nbreak" not in st.texts()


def test_two_prop_ambiguous_group_column_renders_warning() -> None:
    ambiguous = _ambiguous_class()
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no", "yes", "no"],
            "grp": pd.Series(
                [ambiguous("x"), ambiguous("x"), ambiguous("y"), ambiguous("y")], dtype=object
            ),
        }
    )
    st = FakeSt(choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO})
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert st.called("warning")
    # No group selectbox is offered for an ambiguous group set.
    assert st.selectbox_options(runners._TWO_PROP_GROUP_A) is None
    assert "0x" not in st.texts()


# ── architecture + page integration ───────────────────────────────────────────


def test_no_direct_domain_import_in_runner_module() -> None:
    assert "data_quality_toolkit.domain" not in inspect.getsource(runners)


def test_inferential_page_renders_proportion_section_once_with_paired_and_wilcoxon() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "grp": ["x", "y"] * 15,
            "before": np.random.default_rng(0).normal(10, 2, 30),
            "after": np.random.default_rng(1).normal(12, 2, 30),
        }
    )
    st = FakeSt()
    _render_inferential(st, df, dataset_name=None)
    text = st.texts()
    assert "Paired samples — parametric t-test" in text
    assert "Wilcoxon signed-rank" in text
    assert "Proportion tests" in text
    assert text.count("Proportion tests") == 1


# ── opt-in proportion evidence (owner contract) ───────────────────────────


def test_one_proportion_evidence_is_off_by_default() -> None:
    pytest.importorskip("scipy")
    st = FakeSt()

    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)

    assert not st.charts()
    assert runners._ONE_PROP_SHOW_EVIDENCE in [
        k.get("key") for name, _a, k in st.calls if name == "checkbox"
    ]


def test_one_proportion_evidence_matches_the_counts_the_test_used() -> None:
    pytest.importorskip("scipy")
    df = _binary_df(successes=70, failures=30)
    options = _outcome_options(df, "outcome")
    st = FakeSt(
        choices={runners._ONE_PROP_SUCCESS: _option(options, "yes")},
        checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True},
    )

    runners.render_proportion_tests_runner(st, df, 0.05)

    data = st.charts()[0][0]
    assert list(data["label"]) == ["yes [str]"]
    assert list(data["successes"]) == [70]
    assert list(data["total"]) == [100]
    assert list(data["proportion"]) == pytest.approx([0.7])
    assert bool(data.iloc[0]["interval_available"]) is False


def test_one_proportion_evidence_marks_the_null_proportion_as_a_reference() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        numbers={runners._ONE_PROP_NULL: 0.4},
        checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True},
    )

    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)

    spec = st.charts()[0][1]
    reference = [layer for layer in spec["layer"] if layer.get("mark", {}).get("color") == "red"]
    assert reference
    assert reference[0]["encoding"]["y"]["datum"] == pytest.approx(0.4)


def test_two_proportion_evidence_preserves_typed_group_identity() -> None:
    pytest.importorskip("scipy")
    df = pd.DataFrame(
        {
            "outcome": ["yes", "no"] * 20,
            "grp": pd.Series([1, 1, "1", "1"] * 10, dtype=object),
        }
    )
    st = FakeSt(
        choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO},
        checkboxes={runners._TWO_PROP_SHOW_EVIDENCE: True},
    )

    runners.render_proportion_tests_runner(st, df, 0.05)

    data = st.charts()[0][0]
    # int 1 and str "1" stay distinct categories; nothing is merged by text.
    assert list(data["label"]) == ["1 [int]", "1 [str]"]
    assert len(data) == 2


def test_two_proportion_evidence_reports_the_observed_difference() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(
        choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO},
        checkboxes={runners._TWO_PROP_SHOW_EVIDENCE: True},
    )

    runners.render_proportion_tests_runner(st, _two_group_df(), 0.05)

    assert "Observed difference (first minus second)" in st.texts()


def test_proportion_evidence_states_no_interval_is_invented() -> None:
    pytest.importorskip("scipy")
    st = FakeSt(checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True})

    runners.render_proportion_tests_runner(st, _binary_df(), 0.05)

    text = st.texts()
    assert "none are invented" in text
    assert "domain judgement" in text


def test_proportion_evidence_leaves_the_result_contract_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    captured: list[pd.DataFrame] = []

    def fake_download(_st: Any, _label: str, df: pd.DataFrame, _file_name: str) -> None:
        captured.append(df)

    monkeypatch.setattr(runners, "csv_download_button", fake_download)

    runners.render_proportion_tests_runner(FakeSt(), _binary_df(), 0.05)
    runners.render_proportion_tests_runner(
        FakeSt(checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True}), _binary_df(), 0.05
    )

    assert len(captured) == 2
    off, on = captured[0].iloc[0], captured[1].iloc[0]
    for field in (
        "test",
        "statistic",
        "p_value",
        "alpha",
        "alternative",
        "reject_null",
        "success_count",
        "valid_rows",
        "observed_proportion",
    ):
        assert off[field] == on[field]


def test_proportion_evidence_adds_no_download_or_workspace_artifact() -> None:
    pytest.importorskip("scipy")
    off = FakeSt()
    on = FakeSt(checkboxes={runners._ONE_PROP_SHOW_EVIDENCE: True})

    runners.render_proportion_tests_runner(off, _binary_df(), 0.05)
    runners.render_proportion_tests_runner(on, _binary_df(), 0.05)

    def names(st: FakeSt) -> list[str]:
        return [
            k["file_name"] for n, _a, k in st.calls if n == "download_button" and "file_name" in k
        ]

    def buttons(st: FakeSt) -> list[str]:
        return [k["key"] for n, _a, k in st.calls if n == "button" and "key" in k]

    assert names(on) == names(off)
    assert buttons(on) == buttons(off)


# ── F2: binary eligibility, bounded defensive text and grouping bounds ───────

_PATHOLOGICAL_LEVELS = 74_111


def _cardinality_df() -> pd.DataFrame:
    rows = 204
    return pd.DataFrame(
        {
            "outcome": ["yes", "no"] * (rows // 2),
            "three": ["a", "b", "c"] * (rows // 3),
            "fifty": [f"level_{index % 50:05d}" for index in range(rows)],
            "fifty_one": [f"level_{index % 51:05d}" for index in range(rows)],
            "constant": ["only"] * rows,
        }
    )


def _pathological_df() -> pd.DataFrame:
    """A deterministic reproduction of the D4 failure class cardinality."""
    rows = _PATHOLOGICAL_LEVELS
    return pd.DataFrame(
        {
            "outcome": ["yes" if index % 2 else "no" for index in range(rows)],
            "identifier": [f"id_{index:06d}" for index in range(rows)],
        }
    )


def test_binary_outcome_selector_offers_only_two_level_columns() -> None:
    st = FakeSt()
    runners.render_proportion_tests_runner(st, _cardinality_df(), 0.05)
    assert st.selectbox_options(runners._ONE_PROP_OUTCOME) == ["outcome"]


def test_high_cardinality_column_is_not_offered_as_a_binary_outcome() -> None:
    st = FakeSt()
    runners.render_proportion_tests_runner(st, _pathological_df(), 0.05)
    assert st.selectbox_options(runners._ONE_PROP_OUTCOME) == ["outcome"]
    assert "id_000000" not in st.texts()


def test_three_level_defensive_message_is_useful_and_bounded() -> None:
    df = _cardinality_df()
    st = FakeSt(choices={runners._ONE_PROP_OUTCOME: "three"})
    runners.render_proportion_tests_runner(st, df, 0.05)
    text = st.texts()
    assert "This field contains 3 distinct values and is not binary." in text
    assert "exactly two distinct" in text
    assert "a [str], b [str], c [str]" in text
    assert st.selectbox_options(runners._ONE_PROP_SUCCESS) is None


def test_pathological_defensive_message_is_short_and_enumerates_nothing() -> None:
    df = _pathological_df()
    st = FakeSt(choices={runners._ONE_PROP_OUTCOME: "identifier"})
    runners.render_proportion_tests_runner(st, df, 0.05)
    messages = [a[0] for name, a, _k in st.calls if name == "info" and a]
    assert messages
    longest = max(str(message) for message in messages)
    assert "identifier-like" in " ".join(str(message) for message in messages)
    assert "id_000000" not in st.texts()
    assert len(longest) < 400
    assert st.selectbox_options(runners._ONE_PROP_SUCCESS) is None


def test_no_binary_outcome_available_states_the_rule_without_enumeration() -> None:
    df = pd.DataFrame({"identifier": [f"id_{index:06d}" for index in range(120)]})
    st = FakeSt()
    runners.render_proportion_tests_runner(st, df, 0.05)
    text = st.texts()
    assert st.called("info")
    assert "exactly two distinct" in text
    assert "No column in this dataset qualifies." in text
    assert "id_000000" not in text


def test_grouping_selector_accepts_two_to_fifty_levels_and_excludes_wider() -> None:
    st = FakeSt(choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO})
    runners.render_proportion_tests_runner(st, _cardinality_df(), 0.05)
    assert st.selectbox_options(runners._TWO_PROP_GROUP_COLUMN) == ["three", "fifty"]


def test_grouping_selector_excludes_a_pathological_column() -> None:
    st = FakeSt(choices={runners._PROP_MODE_KEY: runners._PROP_MODE_TWO})
    runners.render_proportion_tests_runner(st, _pathological_df(), 0.05)
    assert st.selectbox_options(runners._TWO_PROP_GROUP_COLUMN) is None
    assert st.called("info")
    assert "id_000000" not in st.texts()


# -- F6: stale / session-injected grouping selection is refused pre-allocation --
#
# ``FakeSt.selectbox`` honours ``choices`` by key and ignores the offered options, so
# pinning ``_TWO_PROP_GROUP_COLUMN`` to a column the selector never offered reproduces
# exactly the stale or session-injected selection the page-tier guard exists for.


def _record_typed_category_columns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the column of every ``_typed_categories`` call made during a render."""
    seen: list[str] = []
    original = svc._typed_categories

    def recorder(values: list[Any], column: str) -> Any:
        seen.append(column)
        return original(values, column)

    monkeypatch.setattr(svc, "_typed_categories", recorder)
    return seen


def _forbid_two_proportion_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if a refused grouping selection still reaches the statistical run."""

    def forbidden(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a refused grouping selection reached the statistical service")

    monkeypatch.setattr(runners, "run_two_proportion_z_test", forbidden)


@pytest.fixture(scope="module")
def stale_grouping_frame() -> pd.DataFrame:
    """A legitimate grouping column beside a 51-level and a near-unique companion."""
    rows = _PATHOLOGICAL_LEVELS
    return pd.DataFrame(
        {
            "outcome": ["yes" if index % 2 else "no" for index in range(rows)],
            "grp": [f"group_{index % 3:02d}" for index in range(rows)],
            "identifier": [f"id_{index:06d}" for index in range(rows)],
        }
    )


def test_stale_fifty_one_level_grouping_selection_is_refused_before_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = _cardinality_df()
    seen = _record_typed_category_columns(monkeypatch)
    _forbid_two_proportion_run(monkeypatch)
    st = FakeSt(
        choices={
            runners._PROP_MODE_KEY: runners._PROP_MODE_TWO,
            runners._TWO_PROP_GROUP_COLUMN: "fifty_one",
        }
    )
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert "fifty_one" not in seen
    assert st.selectbox_options(runners._TWO_PROP_GROUP_A) is None
    assert st.selectbox_options(runners._TWO_PROP_GROUP_B) is None
    assert st.called("info")
    text = st.texts()
    assert "more than 50 distinct values" in text
    assert "at most 50 distinct non-missing values" in text
    assert "level_00050" not in text


def test_stale_pathological_grouping_selection_is_refused_before_options(
    stale_grouping_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = _record_typed_category_columns(monkeypatch)
    _forbid_two_proportion_run(monkeypatch)
    st = FakeSt(
        choices={
            runners._PROP_MODE_KEY: runners._PROP_MODE_TWO,
            runners._TWO_PROP_GROUP_COLUMN: "identifier",
        }
    )
    runners.render_proportion_tests_runner(st, stale_grouping_frame, 0.05)
    assert "identifier" not in seen
    assert st.selectbox_options(runners._TWO_PROP_GROUP_A) is None
    assert st.selectbox_options(runners._TWO_PROP_GROUP_B) is None
    assert st.called("info")
    messages = [str(a[0]) for name, a, _k in st.calls if name == "info" and a]
    assert messages
    assert "identifier-like" in " ".join(messages)
    assert max(len(message) for message in messages) < 400
    assert "id_000000" not in st.texts()


def test_grouping_helper_refuses_a_pathological_column_without_materializing(
    stale_grouping_frame: pd.DataFrame, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service helper defends itself even when the page tier is bypassed."""

    def forbidden(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a refused grouping column reached _typed_categories")

    monkeypatch.setattr(svc, "_typed_categories", forbidden)
    options, error = svc.group_category_options(stale_grouping_frame, "identifier")
    assert options == []
    assert error is not None
    assert "identifier-like" in error
    assert "74,111" in error
    assert "id_000000" not in error
    assert len(error) <= 200


def test_stale_fifty_level_grouping_selection_still_proceeds_normally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = _cardinality_df()
    seen = _record_typed_category_columns(monkeypatch)
    st = FakeSt(
        choices={
            runners._PROP_MODE_KEY: runners._PROP_MODE_TWO,
            runners._TWO_PROP_GROUP_COLUMN: "fifty",
        }
    )
    runners.render_proportion_tests_runner(st, df, 0.05)
    assert "fifty" in seen
    assert len(st.selectbox_options(runners._TWO_PROP_GROUP_A) or []) == 50
    assert len(st.selectbox_options(runners._TWO_PROP_GROUP_B) or []) == 49
    assert "at most 50 distinct non-missing values" not in st.texts()


def test_one_proportion_numbers_are_unchanged_for_a_binary_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    df = _binary_df()
    captured: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(
        runners, "csv_download_button", lambda st, label, frame, name: captured.update(df=frame)
    )
    options = _outcome_options(df, "outcome")
    st = FakeSt(choices={runners._ONE_PROP_SUCCESS: _option(options, "yes")})
    runners.render_proportion_tests_runner(st, df, 0.05)
    rendered = captured["df"].iloc[0]
    direct = svc.run_one_proportion_z_test(df, "outcome", "yes", null_proportion=0.5, alpha=0.05)
    assert rendered["statistic"] == pytest.approx(direct["statistic"])
    assert rendered["p_value"] == pytest.approx(direct["p_value"])
    assert rendered["reject_null"] == direct["reject_null"]
    assert rendered["success_count"] == direct["success_count"]


def test_two_proportion_numbers_are_unchanged_for_a_binary_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("scipy")
    df = _two_group_df()
    captured: dict[str, pd.DataFrame] = {}
    monkeypatch.setattr(
        runners, "csv_download_button", lambda st, label, frame, name: captured.update(df=frame)
    )
    st = _two_prop_st(df, "yes", "A", "B")
    runners.render_proportion_tests_runner(st, df, 0.05)
    rendered = captured["df"].iloc[0]
    direct = svc.run_two_proportion_z_test(
        df, "outcome", "yes", "grp", "A", "B", alpha=0.05, alternative="two-sided"
    )
    assert rendered["statistic"] == pytest.approx(direct["statistic"])
    assert rendered["p_value"] == pytest.approx(direct["p_value"])
    assert rendered["reject_null"] == direct["reject_null"]
    assert rendered["proportion_difference"] == pytest.approx(direct["proportion_difference"])


def test_runner_module_has_no_unbounded_category_label_join() -> None:
    source = inspect.getsource(runners)
    assert "', '.join(" not in source
    assert '", ".join(' not in source
