"""Page-integration tests for the Data Overview Smart Preview.

Proves that the preview is built from the result the page has already loaded
(no second read, profile, or assessment), that the active original/managed
identity it shows is privacy-safe, that facts and heuristics stay visibly
distinct, that every existing Data Overview capability survives, that empty and
unavailable states are safe, and that large-file mode stays bounded and never
forces a full materialization.

All frames are deterministic synthetic frames; no fixture dataset is added and
no Streamlit runtime is started.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.pages import data_overview
from data_quality_toolkit.adapters.ui.pages.data_overview import (
    _SMART_PREVIEW_TITLE,
    _render_data_overview,
    _render_large_data_profile_overview,
)
from data_quality_toolkit.adapters.ui.services import managed_frame_loader as _mfl
from data_quality_toolkit.adapters.ui.services import smart_data_overview as sdo
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    MANAGED_TRUST_STATE_KEY,
    commit_trust_root,
    ensure_session_capability,
    get_valid_trust_root,
    make_source_locator,
)
from data_quality_toolkit.adapters.ui.services.smart_data_overview import (
    EVIDENCE_FACT,
    EVIDENCE_HEURISTIC,
    EVIDENCE_LABELS,
    EVIDENCE_SAMPLE,
    EVIDENCE_UNAVAILABLE,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

_MOCK_LOAD_DF = "data_quality_toolkit.adapters.ui.pages.data_overview._load_df_and_assess"
_MOCK_LOAD_CHUNKED = "data_quality_toolkit.adapters.ui.pages.data_overview._load_profile_chunked"
_MOCK_MANAGED_FRAME = "data_quality_toolkit.adapters.ui.pages.data_overview.get_managed_frame"
_MOCK_MANAGED_ASSESS = "data_quality_toolkit.adapters.ui.pages.data_overview.get_managed_assessment"
_MOCK_RUN_PROFILING = "data_quality_toolkit.domain.profiling.profiling_orchestrator.run_profiling"
_MOCK_ASSESS = "data_quality_toolkit.domain.assessment.quality_checker.assess"

_MANAGED_ABS = "C:\\workspace\\versions\\v1\\data.csv"
_PRIVATE_DIR = r"C:\Users\example_user\private"
_LARGE_CHECKBOX_LABEL = "Large-data mode (profile-only, chunked streaming)"


class FakeSt:
    """Streamlit recorder: every call is captured on one object for assertions."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._text_input_vals: dict[str, str] = {}
        self._checkbox_vals: dict[str, bool] = {}

    def __enter__(self) -> FakeSt:
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def __getattr__(self, name: str) -> Any:
        def recorder(*args: Any, **kwargs: Any) -> None:
            self._record(name, *args, **kwargs)

        return recorder

    def columns(self, count: int) -> list[FakeSt]:
        self._record("columns", count)
        return [self for _ in range(count)]

    def expander(self, label: str, **kwargs: Any) -> FakeSt:
        self._record("expander", label, **kwargs)
        return self

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        return False

    def download_button(self, *args: Any, **kwargs: Any) -> None:
        self._record("download_button", *args, **kwargs)

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        return self._text_input_vals.get(label, "")

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        return self._checkbox_vals.get(label, False)

    def number_input(self, label: str, **kwargs: Any) -> Any:
        self._record("number_input", label, **kwargs)
        return kwargs.get("value", kwargs.get("min_value", 1))

    def selectbox(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        self._record("selectbox", label, options, **kwargs)
        return options[0] if options else None

    def set_text_input(self, label: str, value: str) -> FakeSt:
        self._text_input_vals[label] = value
        return self

    def set_checkbox(self, label: str, value: bool) -> FakeSt:
        self._checkbox_vals[label] = value
        return self

    def called(self, name: str) -> bool:
        return any(call[0] == name for call in self.calls)

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call[0] == name)

    def frames(self) -> list[pd.DataFrame]:
        return [
            args[0]
            for name, args, _ in self.calls
            if name == "dataframe" and args and isinstance(args[0], pd.DataFrame)
        ]

    def text(self) -> str:
        return " ".join(
            str(value) for _, args, _ in self.calls for value in args if isinstance(value, str)
        )

    def preview_text(self) -> str:
        """Return only the text the Smart Preview itself rendered.

        The shared dataset-source callout above the preview is a separate,
        pre-existing surface with its own contract, so preview-specific
        assertions must not accidentally measure it.
        """
        whole = self.text()
        marker = whole.find(_SMART_PREVIEW_TITLE)
        return whole[marker:] if marker >= 0 else ""


# ---------------------------------------------------------------------------
# Deterministic synthetic inputs
# ---------------------------------------------------------------------------

_DF = pd.DataFrame(
    {
        "order_id": [f"O{i:03d}" for i in range(12)],
        "signup": [f"2024-01-{i + 1:02d}" for i in range(12)],
        "segment": ["a", "b", "c"] * 4,
        "amount": [float(i) for i in range(12)],
    }
)
_DF.loc[5, "amount"] = None

_PROFILE: dict[str, Any] = {
    "rows": 12,
    "cols": 4,
    "memory_mb": 0.01,
    "columns": [
        {"name": "order_id", "dtype": "object", "nulls": 0, "unique": 12},
        {"name": "signup", "dtype": "object", "nulls": 0, "unique": 12},
        {"name": "segment", "dtype": "object", "nulls": 0, "unique": 3},
        {"name": "amount", "dtype": "float64", "nulls": 1, "unique": 11},
    ],
}
_RESULT: dict[str, Any] = {
    "profile": _PROFILE,
    "assessment": {"score": 0.95, "quality_score": 0.95, "issues": []},
}

_EMPTY_DF = pd.DataFrame({"a": pd.Series(dtype="float64")})
_EMPTY_RESULT: dict[str, Any] = {
    "profile": {
        "rows": 0,
        "cols": 1,
        "memory_mb": 0.0,
        "columns": [{"name": "a", "dtype": "float64", "nulls": 0, "unique": 0}],
    },
    "assessment": {"score": 0.0, "issues": []},
}

_LARGE_ENVELOPE: dict[str, Any] = {
    "profile": {
        "rows": 400_000,
        "cols": 3,
        "memory_mb": None,
        "columns": [
            {"name": "id", "dtype": "int64", "nulls": 0},
            {"name": "val", "dtype": "float64", "nulls": 12},
            {"name": "name", "dtype": "object", "nulls": 3},
        ],
    },
    "approximate": True,
    "unsupported_metrics": ["unique", "memory_mb"],
}


def _context(*, large_file_mode: bool = False) -> DatasetContext:
    return DatasetContext(
        source_path=rf"{_PRIVATE_DIR}\customers.csv",
        display_name="customers.csv",
        size_bytes=4096,
        modified_ns=1,
        large_file_mode=large_file_mode,
    )


@pytest.fixture(autouse=True)
def _clean_managed_caches() -> Any:
    _mfl.clear_managed_caches()
    yield
    _mfl.clear_managed_caches()


def _trusted_session(*, large: bool = False) -> dict[str, Any]:
    """Trusted managed session whose version label deliberately looks path-like."""
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    commit_trust_root(
        state,
        capability,
        version_id="1a2b3c4d-0000-4000-8000-000000000001",
        family_id=str(uuid.uuid4()),
        content_id="sha256:" + "a" * 64,
        root_content_id="sha256:" + "b" * 64,
        parent_version_id=None,
        version_label=rf"{_PRIVATE_DIR}\secret label",
        locator=make_source_locator(
            display_name="data.csv",
            relative_posix="versions/v1/data.csv",
            absolute_path=_MANAGED_ABS,
        ),
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=large,
    )
    return state


def _render_legacy(st: FakeSt, *, state: dict[str, Any] | None = None) -> Any:
    with patch(_MOCK_LOAD_DF, return_value=(_DF, _RESULT, None)) as loader:
        _render_data_overview(st, state if state is not None else {DATASET_CONTEXT: _context()})
    return loader


# ---------------------------------------------------------------------------
# The preview renders from the already-loaded result
# ---------------------------------------------------------------------------


def test_smart_preview_renders_in_full_mode() -> None:
    st = FakeSt()
    _render_legacy(st)
    assert _SMART_PREVIEW_TITLE in st.text()
    assert "Shape (" in st.text()


def test_smart_preview_reuses_the_single_load_without_reprofiling() -> None:
    """No second read, no second profiling pass, no second assessment."""
    st = FakeSt()
    with (
        patch(_MOCK_LOAD_DF, return_value=(_DF, _RESULT, None)) as loader,
        patch(_MOCK_RUN_PROFILING) as profiler,
        patch(_MOCK_ASSESS) as assessor,
        patch(_MOCK_LOAD_CHUNKED) as chunked,
    ):
        _render_data_overview(st, {DATASET_CONTEXT: _context()})
    assert loader.call_count == 1
    profiler.assert_not_called()
    assessor.assert_not_called()
    chunked.assert_not_called()


def test_smart_preview_groups_and_records_are_rendered_as_tables() -> None:
    st = FakeSt()
    _render_legacy(st)
    frames = st.frames()
    grouped = [f for f in frames if "likely_role" in f.columns]
    records = [f for f in frames if "picked_by" in f.columns]
    assert len(grouped) == 1
    assert len(records) == 1
    assert set(records[0]["picked_by"]) <= set(sdo.STRATEGY_TITLES.values())


def test_smart_preview_reports_the_expected_semantic_groups() -> None:
    st = FakeSt()
    _render_legacy(st)
    grouped = next(f for f in st.frames() if "likely_role" in f.columns)
    roles = dict(zip(grouped["column"], grouped["likely_role"]))
    assert roles["order_id"] == sdo.ROLE_TITLES[sdo.ROLE_IDENTIFIER]
    assert roles["signup"] == sdo.ROLE_TITLES[sdo.ROLE_DATETIME]
    assert roles["segment"] == sdo.ROLE_TITLES[sdo.ROLE_CATEGORICAL]
    assert roles["amount"] == sdo.ROLE_TITLES[sdo.ROLE_MEASURE]


def test_record_preview_does_not_mutate_the_loaded_frame() -> None:
    before = _DF.copy(deep=True)
    _render_legacy(FakeSt())
    pd.testing.assert_frame_equal(_DF, before)


# ---------------------------------------------------------------------------
# Facts versus heuristics stay visible
# ---------------------------------------------------------------------------


def test_facts_and_heuristics_are_visibly_distinguishable() -> None:
    st = FakeSt()
    _render_legacy(st)
    text = st.text()
    assert EVIDENCE_LABELS[EVIDENCE_FACT] in text
    assert EVIDENCE_LABELS[EVIDENCE_HEURISTIC] in text
    grouped = next(f for f in st.frames() if "likely_role" in f.columns)
    assert EVIDENCE_LABELS[EVIDENCE_HEURISTIC] in set(grouped["evidence"])


def test_heuristic_roles_are_never_presented_as_schema_truth() -> None:
    st = FakeSt()
    _render_legacy(st)
    text = st.text().lower()
    assert "heuristic suggestions" in text
    assert "not a declared schema" in text


def test_records_are_not_described_as_statistically_representative() -> None:
    st = FakeSt()
    _render_legacy(st)
    assert "not a statistically representative sample" in st.text()


# ---------------------------------------------------------------------------
# Active-version-aware, privacy-safe identity
# ---------------------------------------------------------------------------


def test_legacy_identity_is_shown_without_any_absolute_path() -> None:
    st = FakeSt()
    _render_legacy(st)
    text = st.text()
    assert "Legacy dataset" in text
    assert "customers.csv" in text
    assert _PRIVATE_DIR not in text


def test_managed_identity_shows_short_version_and_hides_path_and_label() -> None:
    """The preview names the managed version from privacy-safe fields only.

    It uses the locator display name and the shortened version id; the
    operator-typed ``version_label`` is free text and is deliberately never
    rendered by the preview, so a label containing a path cannot reach it.
    """
    st = FakeSt()
    session = _trusted_session()
    with (
        patch(_MOCK_MANAGED_FRAME, return_value=_DF),
        patch(_MOCK_MANAGED_ASSESS, return_value=_RESULT),
    ):
        _render_data_overview(st, session)
    preview = st.preview_text()
    assert "Managed version v-1a2b3c4d" in preview
    assert "data.csv" in preview
    assert _PRIVATE_DIR not in preview  # operator-typed version label never rendered
    assert "1a2b3c4d-0000-4000-8000-000000000001" not in preview  # full uuid stays private
    assert "sha256:" not in preview
    assert _MANAGED_ABS not in st.text()  # no absolute path anywhere on the page


def test_managed_render_never_changes_active_lifecycle_state() -> None:
    session = _trusted_session()
    root_before = get_valid_trust_root(session)
    keys_before = set(session)
    with (
        patch(_MOCK_MANAGED_FRAME, return_value=_DF),
        patch(_MOCK_MANAGED_ASSESS, return_value=_RESULT),
    ):
        _render_data_overview(FakeSt(), session)
    assert set(session) == keys_before == {MANAGED_TRUST_STATE_KEY}
    assert get_valid_trust_root(session) is root_before


def test_legacy_render_does_not_write_to_session_state() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _context()}
    _render_legacy(FakeSt(), state=state)
    assert list(state) == [DATASET_CONTEXT]


# ---------------------------------------------------------------------------
# Existing capabilities survive
# ---------------------------------------------------------------------------


def test_existing_overview_sections_remain_available() -> None:
    st = FakeSt()
    _render_legacy(st)
    text = st.text()
    assert st.called("metric")  # quality/completeness cards
    assert "Data Overview" in text  # page title preserved
    assert "Column Analysis" in text
    assert "Dataset Profile" in text
    assert "Duplicate rows:" in text
    assert "Numeric Summary" in text


def test_smart_preview_adds_no_download_write_or_navigation_control() -> None:
    st = FakeSt()
    _render_legacy(st)
    assert st.count("download_button") == 1  # column analysis only (clean assessment)
    assert not st.called("selectbox")
    assert not st.called("scatter_chart")
    assert not st.called("page_link")
    assert not st.called("switch_page")
    # the only buttons are the pre-existing opt-in workspace-save controls
    labels = [args[0] for name, args, _ in st.calls if name == "button" and args]
    assert all("save" in str(label).lower() for label in labels)


def test_duplicate_rows_are_counted_once_and_shared() -> None:
    st = FakeSt()
    frame = pd.concat([_DF, _DF.iloc[[0]]], ignore_index=True)
    result = {**_RESULT, "profile": {**_PROFILE, "rows": 13}}
    with (
        patch(_MOCK_LOAD_DF, return_value=(frame, result, None)),
        patch.object(
            data_overview, "_duplicate_row_count", wraps=data_overview._duplicate_row_count
        ) as counter,
    ):
        _render_data_overview(st, {DATASET_CONTEXT: _context()})
    assert counter.call_count == 1
    assert "Duplicate rows: 1" in st.text()
    assert "fully duplicated row(s)" in st.text()


# ---------------------------------------------------------------------------
# Empty and unavailable states
# ---------------------------------------------------------------------------


def test_zero_row_dataset_renders_a_safe_preview() -> None:
    st = FakeSt()
    with patch(_MOCK_LOAD_DF, return_value=(_EMPTY_DF, _EMPTY_RESULT, None)):
        _render_data_overview(st, {DATASET_CONTEXT: _context()})
    text = st.text()
    assert _SMART_PREVIEW_TITLE in text
    assert "no rows" in text
    assert not any("picked_by" in f.columns for f in st.frames())


def test_no_dataset_selected_never_reaches_the_preview() -> None:
    st = FakeSt()
    _render_data_overview(st, {})
    assert _SMART_PREVIEW_TITLE not in st.text()


def test_load_error_never_reaches_the_preview() -> None:
    st = FakeSt()
    with patch(_MOCK_LOAD_DF, return_value=(None, None, "file not found")):
        _render_data_overview(st, {DATASET_CONTEXT: _context()})
    assert st.called("error")
    assert _SMART_PREVIEW_TITLE not in st.text()


# ---------------------------------------------------------------------------
# Large-file mode honesty
# ---------------------------------------------------------------------------


def test_large_mode_preview_uses_bounded_sample_wording() -> None:
    """Nothing derived from an approximate profile may be labelled an exact fact."""
    st = FakeSt()
    _render_large_data_profile_overview(st, _LARGE_ENVELOPE)
    preview = st.preview_text()
    assert f"Shape ({EVIDENCE_LABELS[EVIDENCE_SAMPLE]})" in preview
    assert f"Shape ({EVIDENCE_LABELS[EVIDENCE_FACT]})" not in preview
    grouped = next(f for f in st.frames() if "likely_role" in f.columns)
    assert EVIDENCE_LABELS[EVIDENCE_FACT] not in set(grouped["evidence"])
    assert EVIDENCE_LABELS[EVIDENCE_SAMPLE] in set(grouped["evidence"])


def test_large_mode_marks_records_unavailable_without_materializing() -> None:
    st = FakeSt()
    with (
        patch(_MOCK_LOAD_DF) as loader,
        patch(_MOCK_MANAGED_FRAME) as managed_frame,
    ):
        _render_large_data_profile_overview(st, _LARGE_ENVELOPE)
    loader.assert_not_called()
    managed_frame.assert_not_called()
    assert "no full DataFrame is loaded" in st.text()
    assert not any("picked_by" in f.columns for f in st.frames())


def test_large_mode_marks_unknown_distinct_counts_as_not_evaluated() -> None:
    st = FakeSt()
    _render_large_data_profile_overview(st, _LARGE_ENVELOPE)
    grouped = next(f for f in st.frames() if "likely_role" in f.columns)
    assert EVIDENCE_LABELS[EVIDENCE_UNAVAILABLE] in set(grouped["evidence"])
    assert grouped["distinct"].isna().all()


def test_managed_large_mode_preview_shows_managed_identity_without_a_path() -> None:
    st = FakeSt()
    session = _trusted_session(large=True)
    with (
        patch(_MOCK_LOAD_CHUNKED, return_value=(_LARGE_ENVELOPE, None)),
        patch(_MOCK_MANAGED_FRAME) as managed_frame,
    ):
        _render_data_overview(st, session)
    managed_frame.assert_not_called()
    text = st.text()
    assert "Managed version v-1a2b3c4d" in text
    assert "large-file profile mode" in text
    assert _MANAGED_ABS not in text


def test_unmanaged_large_mode_preview_reports_the_legacy_identity() -> None:
    st = FakeSt()
    st.set_text_input("CSV path", "data.csv")
    st.set_checkbox(_LARGE_CHECKBOX_LABEL, True)
    with patch(_MOCK_LOAD_CHUNKED, return_value=(_LARGE_ENVELOPE, None)):
        _render_data_overview(st, {})
    preview = st.preview_text()
    assert preview  # the preview rendered
    assert "Legacy dataset" in preview
    assert "large-file profile mode" not in preview  # no context → no mode claim invented
    assert "data.csv" not in preview  # a manually typed path is not an identity


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------


def test_preview_service_lives_in_the_ui_service_layer() -> None:
    assert sdo.__name__.startswith("data_quality_toolkit.adapters.ui.services.")


def test_page_imports_the_preview_from_the_service_layer() -> None:
    assert data_overview.build_smart_overview is sdo.build_smart_overview
    assert data_overview.PreviewIdentity is sdo.PreviewIdentity
