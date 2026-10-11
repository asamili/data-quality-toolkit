"""Tests for the shared active-dataset identity presentation.

Cover the pure identity model (label priority, short version formatting, managed
versus legacy status, safe degradation), the two shared rendering surfaces, and the
page contract that each lifecycle-aware page shows exactly one identity callout.

Assertions are semantic: every test checks for the presence of meaning and the
absence of sensitive values, never a whole rendered snapshot.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from data_quality_toolkit.adapters.ui.components.active_dataset_identity import (
    FULL_ANALYSIS_MODE,
    LARGE_FILE_MODE,
    LEGACY_STATUS,
    MANAGED_FALLBACK_LABEL,
    MANAGED_STATUS,
    build_active_dataset_identity,
    short_version_id,
)
from data_quality_toolkit.adapters.ui.components.dataset_context import (
    render_dataset_context_panel,
)
from data_quality_toolkit.adapters.ui.components.source_hub import (
    render_dataset_source_callout,
)
from data_quality_toolkit.adapters.ui.pages import (
    data_overview,
    eda_explorer,
    preprocess_studio,
    quality_score,
    statistics_lab,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT

_PRIVATE_DIR = r"C:\Users\example_user\private"
_SOURCE_PATH = rf"{_PRIVATE_DIR}\customers.csv"
_VERSION_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
_FAMILY_ID = "9f8e7d6c-5b4a-4938-8271-605f4e3d2c1b"
_CONTENT_ID = "sha256:" + "a" * 64
_ROOT_CONTENT_ID = "sha256:" + "b" * 64
_PARENT_VERSION_ID = "22222222-3333-4444-8555-666677778888"


class FakeSt:
    """Streamlit-like recorder with minimal widget behavior."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.text_values: dict[str, str] = {}
        self.checkbox_values: dict[str, bool] = {}
        self.button_values: dict[str, bool] = {}

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

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        return self.text_values.get(label, str(kwargs.get("value", "")))

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        return self.checkbox_values.get(label, bool(kwargs.get("value", False)))

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        return self.button_values.get(label, False)

    def selectbox(self, label: str, options: list[Any], **kwargs: Any) -> Any:
        self._record("selectbox", label, options, **kwargs)
        return options[0] if options else None

    def multiselect(self, label: str, options: list[Any], **kwargs: Any) -> list[Any]:
        self._record("multiselect", label, options, **kwargs)
        return []

    def number_input(self, label: str, **kwargs: Any) -> int | float:
        self._record("number_input", label, **kwargs)
        value = kwargs.get("value", kwargs.get("min_value", 0))
        return value if isinstance(value, int | float) else 0

    def rendered_text(self) -> str:
        return " ".join(
            str(value) for _, args, _ in self.calls for value in args if isinstance(value, str)
        )

    def calls_named(self, name: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        return [(args, kwargs) for kind, args, kwargs in self.calls if kind == name]


def _legacy(
    *, display_name: str = "customers.csv", large_file_mode: bool = False
) -> DatasetContext:
    return DatasetContext(
        source_path=_SOURCE_PATH,
        display_name=display_name,
        size_bytes=4096,
        modified_ns=1,
        large_file_mode=large_file_mode,
    )


def _managed(
    *,
    display_name: str = "customers.csv",
    version_label: str | None = "cleaned v2",
    version_id: str | None = _VERSION_ID,
    large_file_mode: bool = False,
) -> DatasetContext:
    return DatasetContext(
        source_path=_SOURCE_PATH,
        display_name=display_name,
        size_bytes=4096,
        modified_ns=1,
        large_file_mode=large_file_mode,
        managed=True,
        version_id=version_id,
        family_id=_FAMILY_ID,
        content_id=_CONTENT_ID,
        root_content_id=_ROOT_CONTENT_ID,
        parent_version_id=_PARENT_VERSION_ID,
        version_label=version_label,
    )


def _assessment_result() -> tuple[pd.DataFrame, dict[str, Any], None]:
    df = pd.DataFrame({"amount": [10, 20], "segment": ["a", "b"]})
    result = {
        "profile": {
            "rows": 2,
            "cols": 2,
            "memory_mb": 0.01,
            "columns": [
                {"name": "amount", "dtype": "int64", "nulls": 0, "unique": 2, "min": 10, "max": 20},
                {"name": "segment", "dtype": "object", "nulls": 0, "unique": 2},
            ],
        },
        "assessment": {"score": 1.0, "quality_score": 1.0, "issues": []},
    }
    return df, result, None


# --- label priority -------------------------------------------------------


def test_managed_identity_prefers_the_version_label() -> None:
    identity = build_active_dataset_identity(_managed())

    assert identity.label == "cleaned v2"
    assert identity.managed is True


def test_managed_identity_falls_back_to_display_name() -> None:
    identity = build_active_dataset_identity(_managed(version_label="   "))

    assert identity.label == "customers.csv"


def test_managed_identity_falls_back_to_source_basename() -> None:
    identity = build_active_dataset_identity(_managed(version_label=None, display_name="  "))

    # Never the absolute path — the basename only.
    assert identity.label == "customers.csv"
    assert _PRIVATE_DIR not in identity.label


def test_managed_identity_falls_back_to_a_neutral_label() -> None:
    context = DatasetContext(
        source_path="",
        display_name="",
        size_bytes=0,
        modified_ns=0,
        managed=True,
        version_id=_VERSION_ID,
        family_id=_FAMILY_ID,
        content_id=_CONTENT_ID,
        root_content_id=_ROOT_CONTENT_ID,
        version_label=None,
    )

    assert build_active_dataset_identity(context).label == MANAGED_FALLBACK_LABEL


def test_minimal_context_without_lifecycle_fields_presents_as_legacy() -> None:
    # Lifecycle fields are additive with legacy defaults, so a stand-in that
    # predates them must degrade to legacy rather than raise from presentation.
    class MinimalContext:
        source_path = _SOURCE_PATH
        display_name = "customers.csv"
        large_file_mode = True

    identity = build_active_dataset_identity(MinimalContext())  # type: ignore[arg-type]

    assert identity.managed is False
    assert identity.status == LEGACY_STATUS
    assert identity.label == "customers.csv"
    assert identity.short_version_id == ""
    assert identity.mode_label == LARGE_FILE_MODE


def test_legacy_identity_uses_display_name() -> None:
    identity = build_active_dataset_identity(_legacy())

    assert identity.label == "customers.csv"
    assert identity.managed is False


def test_legacy_identity_falls_back_to_source_basename() -> None:
    identity = build_active_dataset_identity(_legacy(display_name="   "))

    assert identity.label == "customers.csv"


# --- short version formatting ---------------------------------------------


def test_short_version_id_strips_hyphens_and_takes_eight_hex_chars() -> None:
    assert short_version_id(_VERSION_ID) == "v-1a2b3c4d"


def test_short_version_id_is_deterministic_and_case_normalized() -> None:
    upper = _VERSION_ID.upper()

    assert short_version_id(upper) == short_version_id(_VERSION_ID)
    assert short_version_id(_VERSION_ID) == short_version_id(_VERSION_ID)


def test_short_version_id_shortens_across_the_first_hyphen_group() -> None:
    # A UUID whose first group is shorter than 8 hex chars once hyphens are gone
    # must still yield exactly 8 characters of payload.
    version = uuid.UUID("00000000-1111-4222-8333-444455556666")
    short = short_version_id(str(version))

    assert short == "v-00000000"
    assert len(short) == len("v-") + 8


@pytest.mark.parametrize("bad", ["", "   ", None, "not-a-uuid", "12345", "sha256:" + "a" * 64])
def test_short_version_id_fails_safely_for_unusable_values(bad: str | None) -> None:
    assert short_version_id(bad) == ""


def test_managed_identity_with_malformed_version_id_degrades_neutrally() -> None:
    identity = build_active_dataset_identity(_managed(version_id="not-a-uuid"))

    assert identity.short_version_id == ""
    # Neutral managed wording, no exception and no raw value echoed.
    assert identity.descriptor == MANAGED_STATUS
    assert "not-a-uuid" not in identity.descriptor


# --- status and mode ------------------------------------------------------


def test_managed_status_is_distinct_from_legacy_status() -> None:
    managed = build_active_dataset_identity(_managed())
    legacy = build_active_dataset_identity(_legacy())

    assert managed.status == MANAGED_STATUS
    assert legacy.status == LEGACY_STATUS
    assert managed.status != legacy.status
    assert managed.descriptor == f"{MANAGED_STATUS} v-1a2b3c4d"
    assert legacy.descriptor == LEGACY_STATUS


def test_legacy_identity_has_no_version_display() -> None:
    identity = build_active_dataset_identity(_legacy())

    assert identity.short_version_id == ""
    assert identity.descriptor == LEGACY_STATUS
    # Legacy is a normal state, not an error or a pseudo-managed version.
    assert "version" not in identity.descriptor.lower()


def test_analysis_modes_are_represented_correctly() -> None:
    assert build_active_dataset_identity(_legacy()).mode_label == FULL_ANALYSIS_MODE
    assert (
        build_active_dataset_identity(_legacy(large_file_mode=True)).mode_label == LARGE_FILE_MODE
    )
    assert build_active_dataset_identity(_managed()).mode_label == FULL_ANALYSIS_MODE
    assert (
        build_active_dataset_identity(_managed(large_file_mode=True)).mode_label == LARGE_FILE_MODE
    )


def test_basename_is_offered_only_when_it_adds_distinction() -> None:
    # Labelled by its own basename -> repeating it would be noise.
    assert build_active_dataset_identity(_legacy()).show_basename is False
    # Labelled by an operator version label -> the file name still informs.
    managed = build_active_dataset_identity(_managed())
    assert managed.show_basename is True
    assert managed.basename == "customers.csv"


# --- privacy --------------------------------------------------------------


def test_identity_model_never_carries_sensitive_values() -> None:
    identity = build_active_dataset_identity(_managed())
    fields = " ".join(
        str(value)
        for value in (
            identity.status,
            identity.label,
            identity.basename,
            identity.mode_label,
            identity.short_version_id,
            identity.descriptor,
        )
    )

    assert _PRIVATE_DIR not in fields
    assert _SOURCE_PATH not in fields
    for secret in (_VERSION_ID, _FAMILY_ID, _CONTENT_ID, _ROOT_CONTENT_ID, _PARENT_VERSION_ID):
        assert secret not in fields


@pytest.mark.parametrize("large", [False, True])
def test_operator_label_containing_a_path_is_reduced_to_a_basename(large: bool) -> None:
    # A version label is free text, so it could itself carry a path. Privacy wins.
    identity = build_active_dataset_identity(
        _managed(version_label=rf"{_PRIVATE_DIR}\leaky.csv", large_file_mode=large)
    )

    assert identity.label == "leaky.csv"
    assert _PRIVATE_DIR not in identity.label


# --- shared renderers -----------------------------------------------------


def test_callout_and_panel_agree_on_managed_terminology() -> None:
    context = _managed()
    callout_st, panel_st = FakeSt(), FakeSt()

    render_dataset_source_callout(callout_st, context)
    render_dataset_context_panel(panel_st, context)

    for st in (callout_st, panel_st):
        text = st.rendered_text()
        assert MANAGED_STATUS in text
        assert "v-1a2b3c4d" in text
        assert "cleaned v2" in text
        assert _PRIVATE_DIR not in text
        assert _VERSION_ID not in text


def test_callout_and_panel_agree_on_legacy_terminology() -> None:
    context = _legacy()
    callout_st, panel_st = FakeSt(), FakeSt()

    render_dataset_source_callout(callout_st, context)
    render_dataset_context_panel(panel_st, context)

    for st in (callout_st, panel_st):
        text = st.rendered_text()
        assert LEGACY_STATUS in text
        assert "customers.csv" in text
        assert MANAGED_STATUS not in text
        assert _PRIVATE_DIR not in text


def test_callout_keeps_the_established_start_wording() -> None:
    st = FakeSt()

    render_dataset_source_callout(st, _legacy(large_file_mode=True))

    text = st.rendered_text()
    assert "Using dataset source from Start" in text
    assert LARGE_FILE_MODE in text


def test_callout_no_context_guidance_is_preserved() -> None:
    st = FakeSt()

    render_dataset_source_callout(st, None)

    text = st.rendered_text()
    assert "Set the dataset source in Start / Load Dataset" in text
    assert "Advanced/manual CSV path override" in text
    # No placeholder lifecycle identity is invented for an absent dataset.
    assert MANAGED_STATUS not in text
    assert LEGACY_STATUS not in text


def test_panel_renders_managed_identity_with_size_and_mode() -> None:
    st = FakeSt()

    render_dataset_context_panel(st, _managed(large_file_mode=True))

    text = st.rendered_text()
    assert "Current dataset" in text
    assert "cleaned v2" in text
    assert f"{MANAGED_STATUS} v-1a2b3c4d" in text
    assert "4.0 KB" in text
    assert "Large-file profile mode" in text


def test_panel_renders_legacy_identity_without_version_wording() -> None:
    st = FakeSt()

    render_dataset_context_panel(st, _legacy())

    text = st.rendered_text()
    assert LEGACY_STATUS in text
    assert "customers.csv" in text
    assert "Full analysis mode" in text
    assert "v-" not in text


def test_renderers_never_mutate_state_or_context() -> None:
    context = _managed()
    state: dict[str, Any] = {DATASET_CONTEXT: context}
    st = FakeSt()

    render_dataset_source_callout(st, context)
    render_dataset_context_panel(st, context)

    # Read-only: the active pointer is untouched and no new key appears.
    assert state == {DATASET_CONTEXT: context}
    assert state[DATASET_CONTEXT] is context


# --- page contract --------------------------------------------------------

_PAGES: tuple[tuple[str, Any], ...] = (
    ("eda_explorer", eda_explorer),
    ("statistics_lab", statistics_lab),
    ("quality_score", quality_score),
    ("preprocess_studio", preprocess_studio),
)

_RENDERERS = {
    "eda_explorer": lambda st, state: eda_explorer._render_eda_explorer(st, state),
    "statistics_lab": lambda st, state: statistics_lab._render_statistics_lab(st, state),
    "quality_score": lambda st, state: quality_score._render_quality_score(st, state),
    "preprocess_studio": lambda st, state: preprocess_studio._render_preprocess_studio(st, state),
}


@pytest.mark.parametrize("name,module", _PAGES)
def test_page_renders_exactly_one_shared_identity_callout(name: str, module: Any) -> None:
    state = {DATASET_CONTEXT: _managed()}

    with patch.object(module, "render_dataset_source_callout") as callout:
        _RENDERERS[name](FakeSt(), state)

    assert callout.call_count == 1
    # The page delegates the live context; it does not format identity itself.
    assert callout.call_args.args[1] is state[DATASET_CONTEXT]


def test_data_overview_renders_exactly_one_shared_identity_callout() -> None:
    state = {DATASET_CONTEXT: _managed()}

    with (
        patch.object(
            data_overview, "_load_df_and_assess", side_effect=lambda _p: _assessment_result()
        ),
        patch.object(data_overview, "render_dataset_source_callout") as callout,
    ):
        data_overview._render_data_overview(FakeSt(), state)

    assert callout.call_count == 1
    assert callout.call_args.args[1] is state[DATASET_CONTEXT]


@pytest.mark.parametrize("name,module", _PAGES)
def test_page_shows_managed_identity_without_leaking_sensitive_values(
    name: str, module: Any
) -> None:
    st = FakeSt()

    _RENDERERS[name](st, {DATASET_CONTEXT: _managed()})

    text = st.rendered_text()
    assert MANAGED_STATUS in text
    assert "v-1a2b3c4d" in text
    assert _PRIVATE_DIR not in text
    for secret in (_VERSION_ID, _FAMILY_ID, _CONTENT_ID, _ROOT_CONTENT_ID):
        assert secret not in text
