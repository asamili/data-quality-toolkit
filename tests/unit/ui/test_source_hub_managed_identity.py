"""Root-first managed identity in the Source Hub.

Proves that a valid managed trust root names the active dataset even against a
stale ``DATASET_CONTEXT`` or a manually entered path, that a managed-looking
context without valid trust fails closed instead of showing unverified
identity, that unmanaged behavior is untouched, and that every operator-facing
label stays privacy-safe.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.components.source_hub import (
    MANAGED_TRUST_REQUIRED_DETAIL,
    MANAGED_TRUST_REQUIRED_DISPLAY,
    ManagedTrustRoot,
    build_source_summary_items,
    render_dataset_source_callout,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    commit_trust_root,
    ensure_session_capability,
    get_valid_trust_root,
    make_source_locator,
    retire_managed_trust,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.keys import DATASET_CONTEXT, SRC_DATASET_ID
from data_quality_toolkit.shared.text_redaction import PATH_REDACTED_DISPLAY

_MANAGED_ABS = "C:\\private\\workspace\\versions\\v1\\customers.csv"
_VERSION_ID = str(uuid.uuid4())
_FAMILY_ID = str(uuid.uuid4())
_CONTENT_ID = "sha256:" + "a" * 64
_ROOT_CONTENT_ID = "sha256:" + "b" * 64


class FakeSt:
    """Minimal Streamlit recorder."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __getattr__(self, name: str) -> Any:
        def recorder(*args: Any, **_kwargs: Any) -> None:
            self.calls.append((name, args))

        return recorder

    def text(self) -> str:
        return " ".join(str(a) for _, args in self.calls for a in args if isinstance(a, str))


def _trusted_state(
    *, large: bool = False, version_label: str = "cleaned v2"
) -> tuple[dict[str, Any], ManagedTrustRoot]:
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    root = commit_trust_root(
        state,
        capability,
        version_id=_VERSION_ID,
        family_id=_FAMILY_ID,
        content_id=_CONTENT_ID,
        root_content_id=_ROOT_CONTENT_ID,
        parent_version_id=None,
        version_label=version_label,
        locator=make_source_locator(
            display_name="customers.csv",
            relative_posix="preprocessed/customers.csv",
            absolute_path=_MANAGED_ABS,
        ),
        size_bytes=2048,
        modified_ns=10,
        large_file_mode=large,
    )
    return state, root


def _stale_context() -> DatasetContext:
    return DatasetContext(
        source_path="C:/elsewhere/previous.csv",
        display_name="previous.csv",
        size_bytes=1,
        modified_ns=1,
    )


def _managed_mirror() -> DatasetContext:
    return DatasetContext(
        source_path=_MANAGED_ABS,
        display_name="customers.csv",
        size_bytes=2048,
        modified_ns=10,
        managed=True,
        version_id=_VERSION_ID,
        family_id=_FAMILY_ID,
        content_id=_CONTENT_ID,
        root_content_id=_ROOT_CONTENT_ID,
        version_label="cleaned v2",
    )


def _dataset_row(items: tuple[Any, ...]) -> Any:
    return next(item for item in items if item.label == "Dataset source")


# --- A. Managed authority ------------------------------------------------------


def test_valid_trust_names_the_dataset_row() -> None:
    state, root = _trusted_state()

    row = _dataset_row(build_source_summary_items(state))

    assert row.primary == "customers.csv"
    assert root.version_label in row.detail
    assert [badge.status for badge in row.badges] == ["ok"]


def test_valid_trust_overrides_stale_dataset_context() -> None:
    state, _root = _trusted_state()
    state[DATASET_CONTEXT] = _stale_context()

    row = _dataset_row(build_source_summary_items(state))

    assert row.primary == "customers.csv"
    assert "previous.csv" not in row.primary


def test_valid_trust_overrides_explicitly_passed_context() -> None:
    state, _root = _trusted_state()

    row = _dataset_row(build_source_summary_items(state, _stale_context()))

    assert row.primary == "customers.csv"


def test_manual_path_cannot_override_valid_trust() -> None:
    state, _root = _trusted_state()
    state[SRC_DATASET_ID] = "sha1:manually-entered"
    state[DATASET_CONTEXT] = DatasetContext(
        source_path="C:/manual/override.csv",
        display_name="override.csv",
        size_bytes=5,
        modified_ns=5,
    )

    row = _dataset_row(build_source_summary_items(state))

    assert row.primary == "customers.csv"
    assert "override.csv" not in row.primary


# --- B. Fail-closed -------------------------------------------------------------


def test_managed_mirror_without_trust_fails_closed() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _managed_mirror()}

    row = _dataset_row(build_source_summary_items(state))

    assert row.primary == MANAGED_TRUST_REQUIRED_DISPLAY
    assert [badge.status for badge in row.badges] == ["missing"]
    assert "customers.csv" not in row.primary


def test_retired_trust_fails_closed_even_with_mirror_left_behind() -> None:
    state, _root = _trusted_state()
    mirror = _managed_mirror()
    retire_managed_trust(state)
    state[DATASET_CONTEXT] = mirror  # physical marker deliberately not cleaned

    row = _dataset_row(build_source_summary_items(state))

    assert row.primary == MANAGED_TRUST_REQUIRED_DISPLAY


def test_fail_closed_row_leaks_no_identity_material() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _managed_mirror()}

    row = _dataset_row(build_source_summary_items(state))
    text = f"{row.primary} {row.detail} {row.raw_value}"

    for secret in (_MANAGED_ABS, _VERSION_ID, _FAMILY_ID, _CONTENT_ID, _ROOT_CONTENT_ID):
        assert secret not in text


# --- C. Unmanaged preservation ---------------------------------------------------


def test_unmanaged_context_row_is_unchanged() -> None:
    context = _stale_context()
    state: dict[str, Any] = {DATASET_CONTEXT: context}

    row = _dataset_row(build_source_summary_items(state))

    assert row.primary == "previous.csv"
    assert [badge.status for badge in row.badges] == ["ok"]


def test_no_dataset_at_all_reports_not_loaded() -> None:
    row = _dataset_row(build_source_summary_items({}))

    assert row.primary == "No dataset selected"
    assert [badge.status for badge in row.badges] == ["missing"]


# --- D. Privacy of the managed row -------------------------------------------------


def test_managed_row_never_carries_the_absolute_path() -> None:
    state, _root = _trusted_state()

    row = _dataset_row(build_source_summary_items(state))
    text = f"{row.primary} {row.detail} {row.raw_value}"

    assert _MANAGED_ABS not in text
    assert "C:\\private" not in text
    # Even the non-display raw value stays workspace-relative.
    assert row.raw_value == "preprocessed/customers.csv"


def test_managed_row_never_carries_lifecycle_identifiers() -> None:
    state, _root = _trusted_state()

    row = _dataset_row(build_source_summary_items(state))
    text = f"{row.primary} {row.detail} {row.raw_value}"

    for secret in (_VERSION_ID, _FAMILY_ID, _CONTENT_ID, _ROOT_CONTENT_ID):
        assert secret not in text


# --- E. Root-first callout ------------------------------------------------------------


def test_callout_reports_trusted_managed_identity() -> None:
    state, root = _trusted_state()
    st = FakeSt()

    render_dataset_source_callout(st, _stale_context(), session_state=state)

    text = st.text()
    assert root.version_label in text
    assert "customers.csv" in text
    assert "previous.csv" not in text  # stale mirror never named
    assert _MANAGED_ABS not in text


def test_callout_reports_managed_mode_label() -> None:
    state, _root = _trusted_state(large=True)
    st = FakeSt()

    render_dataset_source_callout(st, None, session_state=state)

    assert "large-file" in st.text()


def test_callout_fails_closed_for_untrusted_managed_mirror() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _managed_mirror()}
    st = FakeSt()

    render_dataset_source_callout(st, _managed_mirror(), session_state=state)

    text = st.text()
    assert MANAGED_TRUST_REQUIRED_DETAIL in text
    assert _VERSION_ID not in text
    assert _MANAGED_ABS not in text


def test_callout_without_session_state_preserves_legacy_contract() -> None:
    st = FakeSt()

    render_dataset_source_callout(st, _stale_context())

    text = st.text()
    assert "previous.csv" in text
    assert MANAGED_TRUST_REQUIRED_DETAIL not in text


@pytest.mark.parametrize("passed_context", [None, "stale", "mirror"])
def test_valid_trust_wins_regardless_of_passed_context(passed_context: str | None) -> None:
    state, _root = _trusted_state()
    context = {
        None: None,
        "stale": _stale_context(),
        "mirror": _managed_mirror(),
    }[passed_context]
    st = FakeSt()

    render_dataset_source_callout(st, context, session_state=state)

    assert "customers.csv" in st.text()


def test_summary_build_never_mutates_session_state() -> None:
    state, _root = _trusted_state()
    before = dict(state)

    build_source_summary_items(state)

    assert state == before


# --- F. Operator-entered version label safety (R7A3D / F7) ------------------------

# Synthetic only - never a real local path.
_LABEL_PRIVATE_DIR = r"C:\Users\example_user\private_runtime"
_WINDOWS_LABEL = rf"{_LABEL_PRIVATE_DIR}\dataset-v3.csv"
_POSIX_LABEL = "/home/example_user/private_runtime/dataset-v3.csv"

_Render = Callable[[dict[str, Any]], str]


def _callout_text(state: dict[str, Any]) -> str:
    """Render site 1: the trusted managed branch of the dataset source callout."""
    st = FakeSt()
    render_dataset_source_callout(st, None, session_state=state)
    return st.text()


def _row_text(state: dict[str, Any]) -> str:
    """Render site 2: the managed Source Hub summary row."""
    row = _dataset_row(build_source_summary_items(state))
    return f"{row.primary} {row.detail} {row.raw_value}"


_RENDERS: tuple[_Render, ...] = (_callout_text, _row_text)
_RENDER_IDS = ("callout", "summary_row")


@pytest.mark.parametrize("render", _RENDERS, ids=_RENDER_IDS)
@pytest.mark.parametrize(
    ("label", "forbidden"),
    [
        (_WINDOWS_LABEL, ("C:\\", "Users", "example_user", "private_runtime")),
        (_POSIX_LABEL, ("/home/", "example_user", "private_runtime")),
    ],
    ids=["windows", "posix"],
)
def test_path_shaped_version_label_never_exposes_parent_path(
    render: _Render, label: str, forbidden: tuple[str, ...]
) -> None:
    # A version label is operator-typed free text, so it can itself carry a path.
    state, _root = _trusted_state(version_label=label)

    text = render(state)

    for token in forbidden:
        assert token not in text
    assert "dataset-v3.csv" in text  # safe identity survives


@pytest.mark.parametrize("render", _RENDERS, ids=_RENDER_IDS)
@pytest.mark.parametrize("label", ["Production baseline v3", "Validated August snapshot"])
def test_ordinary_version_label_stays_readable(render: _Render, label: str) -> None:
    state, _root = _trusted_state(version_label=label)

    assert label in render(state)


@pytest.mark.parametrize("render", _RENDERS, ids=_RENDER_IDS)
def test_already_redacted_version_label_is_not_redacted_twice(render: _Render) -> None:
    state, _root = _trusted_state(version_label=PATH_REDACTED_DISPLAY)

    assert render(state).count(PATH_REDACTED_DISPLAY) == 1


def test_safe_display_never_mutates_the_stored_version_label() -> None:
    state, root = _trusted_state(version_label=_WINDOWS_LABEL)

    _callout_text(state)
    _row_text(state)

    stored = get_valid_trust_root(state)
    assert stored is not None
    assert stored.version_label == _WINDOWS_LABEL
    assert root.version_label == _WINDOWS_LABEL
