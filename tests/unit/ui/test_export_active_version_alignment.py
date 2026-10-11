"""Focused tests for Export source alignment with the active dataset (gate P5A).

Pins three linked contracts:

* a genuine dataset switch invalidates the auto-seeded Export source, so the next
  Export cannot silently run against the previous dataset;
* the effective Export source is classified against the active DatasetContext, and
  active managed lifecycle identities attach only to a genuinely matching source;
* a historical Latest Export is *labelled* matching or mismatching against the
  currently active dataset — never cleared, and never relabelled as active.
"""

from __future__ import annotations

import inspect
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from data_quality_toolkit.adapters.ui.services.dataset_activation import (
    activate_dataset_context,
    clear_dataset_context,
    make_managed_context,
)
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    CreationMechanism,
    DatasetFormat,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    new_family_id,
    new_version_id,
)
from data_quality_toolkit.adapters.ui.services.export_alignment import (
    MANAGED_SOURCE_ORIGIN,
    ExportSourceStatus,
    LatestExportMatch,
    classify_export_source,
    classify_verified_managed_export_source,
    compare_latest_export,
    export_source_warning,
    latest_export_match_label,
    managed_manifest_metadata,
    normalize_source_binding,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.export_context import (
    ExportArtifactContext,
    export_artifact_context_from_result,
)
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    DATASET_DERIVED_STATE_KEYS,
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
    SRC_EXPORT_OUT_DIR,
    SRC_SESSIONS_ROOT,
    SRC_WORKSPACE_ROOT,
)
from data_quality_toolkit.shared.managed_export_source import VerifiedManagedExportSource

_ACTIVE_PATH = r"C:\Users\example_user\private\active.csv"
_OTHER_PATH = r"C:\Users\example_user\private\other.csv"
_OUT_DIR = r"C:\Users\example_user\private\dist"

_CONTENT_A = "sha256:" + "a" * 64
_CONTENT_B = "sha256:" + "b" * 64
_ROOT = "sha256:" + "c" * 64


# ── Fixtures ────────────────────────────────────────────────────────────────


def _legacy(path: str = _ACTIVE_PATH) -> DatasetContext:
    return DatasetContext(
        source_path=path, display_name="active.csv", size_bytes=2048, modified_ns=10
    )


def _record(
    *,
    version_id: str | None = None,
    family_id: str | None = None,
    content_id: str = _CONTENT_A,
) -> DatasetVersionRecord:
    return DatasetVersionRecord(
        schema_version=1,
        version_id=version_id or new_version_id(),
        family_id=family_id or new_family_id(),
        root_content_id=_ROOT,
        content_id=content_id,
        dataset_id="sha1:" + "d" * 40,
        label="cleaned v2",
        file_relative_path="versions/v1/data.csv",
        format=DatasetFormat.CSV,
        size_bytes=2048,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        created_by=CreationMechanism.PREPROCESS_RECIPE,
        parent=ParentRef(version_id=None, content_id=_ROOT),
        recipe=RecipeRef(digest="sha256:" + "e" * 64, relative_path="recipes/v1.json"),
    )


def _managed(path: str = _ACTIVE_PATH, **overrides: Any) -> DatasetContext:
    return make_managed_context(
        _record(**overrides),
        source_path=path,
        display_name="active.csv",
        size_bytes=2048,
        modified_ns=10,
    )


def _export_result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_id": "run-p5a-1",
        "dataset_id": "sha1:exported",
        "ts": "2026-07-17T10:00:00Z",
        "export_paths": {"dim_dataset": _OUT_DIR + r"\star\dim_dataset.csv"},
    }
    result.update(overrides)
    return result


# ── A. Export source invalidation ───────────────────────────────────────────


def test_export_csv_path_is_declared_dataset_derived() -> None:
    assert EXPORT_CSV_PATH in DATASET_DERIVED_STATE_KEYS


def test_first_activation_keeps_a_pre_entered_export_source() -> None:
    # No dataset was active, so the operator's typed Export path is not stale
    # against anything and must survive the first activation.
    state: dict[str, Any] = {EXPORT_CSV_PATH: _OTHER_PATH}

    activate_dataset_context(state, _legacy(_ACTIVE_PATH))

    assert state[EXPORT_CSV_PATH] == _OTHER_PATH


def test_export_reseeds_from_the_newly_active_dataset_after_a_genuine_switch() -> None:
    from data_quality_toolkit.adapters.ui.pages import export

    state: dict[str, Any] = {}
    activate_dataset_context(state, _legacy(_ACTIVE_PATH))
    state[EXPORT_CSV_PATH] = _ACTIVE_PATH

    # A genuine switch invalidates the stale auto-seeded source ...
    activate_dataset_context(state, _legacy(_OTHER_PATH))
    assert EXPORT_CSV_PATH not in state

    # ... and the next Export render seeds it from the new active context.
    export._seed_export_defaults(_FakeSt(state))
    assert state[EXPORT_CSV_PATH] == _OTHER_PATH


class _FakeSt:
    """Minimal Streamlit stand-in exposing only session_state and no-op widgets."""

    def __init__(self, session_state: dict[str, Any]) -> None:
        self.session_state = session_state

    def __getattr__(self, _name: str) -> Any:
        def recorder(*_args: Any, **_kwargs: Any) -> None:
            return None

        return recorder


def test_genuine_dataset_switch_clears_stale_export_source() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy(_ACTIVE_PATH),
        EXPORT_CSV_PATH: _ACTIVE_PATH,
    }

    result = activate_dataset_context(state, _legacy(_OTHER_PATH))

    assert result.changed is True
    assert EXPORT_CSV_PATH not in state
    assert EXPORT_CSV_PATH in result.cleared_keys


def test_switch_to_managed_version_clears_stale_export_source() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy(_ACTIVE_PATH),
        EXPORT_CSV_PATH: _ACTIVE_PATH,
    }

    activate_dataset_context(state, _managed(_ACTIVE_PATH))

    # Same path, but a managed version is a different binding — the Export source
    # must be reseeded from the new active context rather than assumed current.
    assert EXPORT_CSV_PATH not in state


def test_same_binding_rerun_preserves_manual_override() -> None:
    context = _legacy(_ACTIVE_PATH)
    state: dict[str, Any] = {DATASET_CONTEXT: context, EXPORT_CSV_PATH: _OTHER_PATH}

    result = activate_dataset_context(state, _legacy(_ACTIVE_PATH))

    assert result.changed is False
    assert state[EXPORT_CSV_PATH] == _OTHER_PATH


def test_clearing_dataset_context_clears_export_source() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _legacy(), EXPORT_CSV_PATH: _ACTIVE_PATH}

    assert clear_dataset_context(state) is True
    assert EXPORT_CSV_PATH not in state


def test_switch_preserves_unrelated_workspace_and_output_settings() -> None:
    state: dict[str, Any] = {
        DATASET_CONTEXT: _legacy(_ACTIVE_PATH),
        EXPORT_CSV_PATH: _ACTIVE_PATH,
        SRC_WORKSPACE_ROOT: r"C:\ws",
        SRC_EXPORT_OUT_DIR: _OUT_DIR,
        SRC_SESSIONS_ROOT: r"C:\ws\sessions",
        EXPORT_OUT_DIR: _OUT_DIR,
    }

    activate_dataset_context(state, _legacy(_OTHER_PATH))

    assert state[SRC_WORKSPACE_ROOT] == r"C:\ws"
    assert state[SRC_EXPORT_OUT_DIR] == _OUT_DIR
    assert state[SRC_SESSIONS_ROOT] == r"C:\ws\sessions"
    assert state[EXPORT_OUT_DIR] == _OUT_DIR


# ── B. Alignment classification ─────────────────────────────────────────────


def test_active_managed_source_classifies_as_managed_match() -> None:
    context = _managed()

    alignment = classify_export_source(_ACTIVE_PATH, context)

    assert alignment.status is ExportSourceStatus.ACTIVE_MANAGED
    assert alignment.matches_active_source is True
    assert alignment.may_attach_lifecycle_identity is True
    assert alignment.should_warn is False
    assert alignment.version_id == context.version_id
    assert alignment.family_id == context.family_id
    assert alignment.content_id == context.content_id


def test_active_legacy_source_classifies_as_legacy_match_without_lifecycle_ids() -> None:
    alignment = classify_export_source(_ACTIVE_PATH, _legacy())

    assert alignment.status is ExportSourceStatus.ACTIVE_LEGACY
    assert alignment.matches_active_source is True
    assert alignment.may_attach_lifecycle_identity is False
    assert alignment.should_warn is False
    assert (alignment.version_id, alignment.family_id, alignment.content_id) == ("", "", "")


def test_manual_override_classifies_separately_and_inherits_no_lifecycle_ids() -> None:
    alignment = classify_export_source(_OTHER_PATH, _managed())

    assert alignment.status is ExportSourceStatus.EXPLICIT_OVERRIDE
    assert alignment.matches_active_source is False
    assert alignment.may_attach_lifecycle_identity is False
    assert alignment.should_warn is True
    assert (alignment.version_id, alignment.family_id, alignment.content_id) == ("", "", "")


def test_no_active_dataset_is_handled_without_warning() -> None:
    alignment = classify_export_source(_ACTIVE_PATH, None)

    assert alignment.status is ExportSourceStatus.NO_ACTIVE_DATASET
    assert alignment.matches_active_source is False
    assert alignment.may_attach_lifecycle_identity is False
    # Nothing is active, so there is nothing for the source to differ from.
    assert alignment.should_warn is False


def test_blank_source_does_not_warn() -> None:
    alignment = classify_export_source("   ", _managed())

    assert alignment.source_present is False
    assert alignment.should_warn is False
    assert export_source_warning(alignment) == ""


def test_equivalent_path_spelling_still_matches_active_source() -> None:
    # Both spellings are built host-natively: classification normalizes through
    # os.path, so Windows literals would not collapse on a POSIX runner.
    base = os.path.join(os.sep, "data")
    context = _legacy(os.path.join(base, ".", "active.csv"))

    alignment = classify_export_source(os.path.join(base, "sub", "..", "active.csv"), context)

    assert alignment.status is ExportSourceStatus.ACTIVE_LEGACY


def test_normalize_source_binding_is_blank_safe() -> None:
    assert normalize_source_binding(None) == ""
    assert normalize_source_binding("   ") == ""


def test_override_warning_names_only_a_basename() -> None:
    alignment = classify_export_source(_OTHER_PATH, _managed())

    message = export_source_warning(alignment)

    assert "other.csv" in message
    assert r"C:\Users\example_user" not in message
    assert _OTHER_PATH not in message
    assert "not the active managed version" in message


# ── C/D. Export context source linkage ──────────────────────────────────────


def test_managed_matching_export_stores_lifecycle_linkage() -> None:
    context = _managed()
    alignment = classify_export_source(_ACTIVE_PATH, context)

    stored = export_artifact_context_from_result(_export_result(), _OUT_DIR, alignment)

    assert stored is not None
    assert stored.source_status == ExportSourceStatus.ACTIVE_MANAGED.value
    assert stored.source_version_id == context.version_id
    assert stored.source_family_id == context.family_id
    assert stored.source_content_id == context.content_id
    assert stored.source_display_name == "active.csv"
    # The export's own compatibility dataset_id still comes from the run itself.
    assert stored.dataset_id == "sha1:exported"


def test_legacy_matching_export_fabricates_no_lifecycle_ids() -> None:
    alignment = classify_export_source(_ACTIVE_PATH, _legacy())

    stored = export_artifact_context_from_result(_export_result(), _OUT_DIR, alignment)

    assert stored is not None
    assert stored.source_status == ExportSourceStatus.ACTIVE_LEGACY.value
    assert stored.source_version_id == ""
    assert stored.source_family_id == ""
    assert stored.source_content_id == ""


def test_override_export_stores_evidence_without_active_lifecycle_ids() -> None:
    alignment = classify_export_source(_OTHER_PATH, _managed())

    stored = export_artifact_context_from_result(_export_result(), _OUT_DIR, alignment)

    assert stored is not None
    assert stored.source_status == ExportSourceStatus.EXPLICIT_OVERRIDE.value
    assert stored.source_version_id == ""
    assert stored.source_family_id == ""
    assert stored.source_content_id == ""
    assert stored.source_display_name == "other.csv"
    assert stored.dataset_id == "sha1:exported"


def test_lifecycle_ids_are_stripped_even_from_a_mislabelled_alignment() -> None:
    from data_quality_toolkit.adapters.ui.services.export_alignment import ExportSourceAlignment

    # A caller that hands over an override carrying identities must not be able to
    # smuggle them onto the export context.
    smuggled = ExportSourceAlignment(
        status=ExportSourceStatus.EXPLICIT_OVERRIDE,
        display_name="other.csv",
        binding=normalize_source_binding(_OTHER_PATH),
        source_present=True,
        version_id=new_version_id(),
        family_id=new_family_id(),
        content_id=_CONTENT_A,
    )

    stored = export_artifact_context_from_result(_export_result(), _OUT_DIR, smuggled)

    assert stored is not None
    assert stored.source_version_id == ""
    assert stored.source_family_id == ""
    assert stored.source_content_id == ""


def test_context_without_alignment_remains_valid_and_unlinked() -> None:
    stored = export_artifact_context_from_result(_export_result(), _OUT_DIR)

    assert stored is not None
    assert stored.source_status == ""
    assert stored.source_binding == ""
    assert stored.run_id == "run-p5a-1"


# ── E. Latest Export comparison ─────────────────────────────────────────────


def _stored_for(source_path: str, context: DatasetContext | None) -> ExportArtifactContext:
    alignment = classify_export_source(source_path, context)
    stored = export_artifact_context_from_result(_export_result(), _OUT_DIR, alignment)
    assert stored is not None
    return stored


def test_exact_managed_version_match() -> None:
    active = _managed()
    stored = _stored_for(_ACTIVE_PATH, active)

    assert compare_latest_export(stored, active) is LatestExportMatch.MATCHES_ACTIVE_MANAGED


def test_same_path_but_different_managed_version_is_mismatch() -> None:
    family = new_family_id()
    exported_from = _managed(family_id=family)
    now_active = _managed(family_id=family)
    assert exported_from.version_id != now_active.version_id
    assert exported_from.source_path == now_active.source_path

    stored = _stored_for(_ACTIVE_PATH, exported_from)

    assert compare_latest_export(stored, now_active) is LatestExportMatch.OTHER_DATASET


def test_same_version_id_but_different_content_id_is_mismatch() -> None:
    version_id, family_id = new_version_id(), new_family_id()
    exported_from = _managed(version_id=version_id, family_id=family_id, content_id=_CONTENT_A)
    now_active = _managed(version_id=version_id, family_id=family_id, content_id=_CONTENT_B)

    stored = _stored_for(_ACTIVE_PATH, exported_from)

    assert compare_latest_export(stored, now_active) is LatestExportMatch.OTHER_DATASET


def test_matching_legacy_source_matches() -> None:
    active = _legacy(_ACTIVE_PATH)
    stored = _stored_for(_ACTIVE_PATH, active)

    assert compare_latest_export(stored, active) is LatestExportMatch.MATCHES_ACTIVE_LEGACY


def test_different_legacy_source_is_mismatch() -> None:
    stored = _stored_for(_ACTIVE_PATH, _legacy(_ACTIVE_PATH))

    assert compare_latest_export(stored, _legacy(_OTHER_PATH)) is LatestExportMatch.OTHER_DATASET


def test_managed_export_against_no_active_dataset() -> None:
    stored = _stored_for(_ACTIVE_PATH, _managed())

    assert compare_latest_export(stored, None) is LatestExportMatch.NO_ACTIVE_DATASET


def test_override_export_never_claims_the_active_managed_version() -> None:
    active = _managed()
    stored = _stored_for(_OTHER_PATH, active)

    assert compare_latest_export(stored, active) is LatestExportMatch.OTHER_DATASET


def test_older_context_without_linkage_reports_unavailable() -> None:
    older = ExportArtifactContext(
        export_paths={"dim_dataset": _OUT_DIR + r"\star\dim_dataset.csv"},
        output_dir=_OUT_DIR,
        run_id="run-old",
        dataset_id="sha1:old",
    )

    assert compare_latest_export(older, _managed()) is LatestExportMatch.INSUFFICIENT_LINKAGE
    assert compare_latest_export(older, _legacy()) is LatestExportMatch.INSUFFICIENT_LINKAGE


def test_comparison_never_mutates_the_historical_context() -> None:
    active = _managed()
    stored = _stored_for(_ACTIVE_PATH, active)
    before = (stored.run_id, stored.source_status, stored.source_version_id)

    compare_latest_export(stored, _legacy(_OTHER_PATH))

    assert (stored.run_id, stored.source_status, stored.source_version_id) == before


@pytest.mark.parametrize(
    ("match", "expected"),
    [
        (LatestExportMatch.MATCHES_ACTIVE_MANAGED, "Matches active dataset"),
        (LatestExportMatch.MATCHES_ACTIVE_LEGACY, "Matches active dataset"),
        (LatestExportMatch.OTHER_DATASET, "Exported from another dataset"),
        (LatestExportMatch.NO_ACTIVE_DATASET, "No active dataset for comparison"),
        (
            LatestExportMatch.INSUFFICIENT_LINKAGE,
            "Source match unavailable for this older export",
        ),
    ],
)
def test_match_labels_are_fixed_and_identity_free(match: LatestExportMatch, expected: str) -> None:
    label = latest_export_match_label(match)

    assert label == expected
    assert "C:" not in label
    assert "sha256" not in label
    assert "sha1" not in label


def test_every_match_state_has_a_label() -> None:
    for match in LatestExportMatch:
        assert latest_export_match_label(match)


# --- managed alignment sibling ---------------------------------------------

_MANAGED_ABS = "C:\\private\\ws\\preprocessed\\customers.csv"


def _verified_source(**overrides: object) -> VerifiedManagedExportSource:
    values: dict[str, object] = {
        "version_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "content_id": "sha256:" + "a" * 64,
        "root_content_id": "sha256:" + "b" * 64,
        "parent_version_id": None,
        "version_label": "cleaned v2",
        "display_name": "customers.csv",
        "relative_posix": "preprocessed/customers.csv",
        "size_bytes": 2048,
        "modified_ns": 10,
        "large_file_mode": False,
        "source_path": _MANAGED_ABS,
    }
    values.update(overrides)
    return VerifiedManagedExportSource(**values)  # type: ignore[arg-type]


def test_managed_alignment_accepts_exactly_one_provenance_object() -> None:
    signature = inspect.signature(classify_verified_managed_export_source)

    assert list(signature.parameters) == ["source"]
    forbidden = {
        "source_path",
        "context",
        "version_id",
        "family_id",
        "content_id",
        "df",
        "artifact_meta",
        "trust_root",
    }
    assert forbidden.isdisjoint(set(signature.parameters))


def test_legacy_classifier_signature_is_unchanged() -> None:
    signature = inspect.signature(classify_export_source)

    assert list(signature.parameters) == ["source_path", "context"]
    assert "source" not in signature.parameters


def test_verified_managed_source_is_always_active_managed() -> None:
    alignment = classify_verified_managed_export_source(_verified_source())

    assert alignment.status is ExportSourceStatus.ACTIVE_MANAGED
    assert alignment.matches_active_source is True
    assert alignment.may_attach_lifecycle_identity is True
    assert alignment.should_warn is False


def test_verified_managed_alignment_carries_the_verified_identities() -> None:
    source = _verified_source()

    alignment = classify_verified_managed_export_source(source)

    assert alignment.version_id == source.version_id
    assert alignment.family_id == source.family_id
    assert alignment.content_id == source.content_id
    assert alignment.display_name == source.display_name
    assert alignment.source_present is True


def test_verified_managed_alignment_projects_manifest_metadata() -> None:
    source = _verified_source()

    metadata = managed_manifest_metadata(classify_verified_managed_export_source(source))

    assert metadata == {
        "source_version_id": source.version_id,
        "source_family_id": source.family_id,
        "source_content_id": source.content_id,
        "source_origin": MANAGED_SOURCE_ORIGIN,
    }


def test_verified_managed_metadata_never_carries_a_path() -> None:
    source = _verified_source()

    metadata = managed_manifest_metadata(classify_verified_managed_export_source(source))

    assert metadata is not None
    serialized = json.dumps(metadata)
    assert _MANAGED_ABS not in serialized
    assert "C:\\" not in serialized
    assert source.relative_posix not in serialized


def test_verified_managed_alignment_display_name_is_basename_only() -> None:
    alignment = classify_verified_managed_export_source(_verified_source())

    assert alignment.display_name == "customers.csv"
    assert os.sep not in alignment.display_name
    assert "/" not in alignment.display_name


def test_managed_alignment_emits_no_override_warning() -> None:
    alignment = classify_verified_managed_export_source(_verified_source())

    assert export_source_warning(alignment) == ""


def test_manual_path_cannot_reach_the_managed_classifier() -> None:
    """Root-first: verified provenance decides identity; no path is compared."""
    source = _verified_source()
    relocated = _verified_source(
        version_id=source.version_id,
        family_id=source.family_id,
        content_id=source.content_id,
        source_path="D:\\somewhere\\else\\customers.csv",
    )

    alignment = classify_verified_managed_export_source(relocated)

    # Identity comes from the verified provenance, never from path comparison.
    assert alignment.status is ExportSourceStatus.ACTIVE_MANAGED
    assert alignment.version_id == source.version_id
    assert alignment.content_id == source.content_id
