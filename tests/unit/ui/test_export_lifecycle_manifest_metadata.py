"""Focused tests for lifecycle metadata threaded into export manifests (gate P5C).

An export produced from the active managed version records *which* version it came
from, in the manifest itself, so the evidence survives the session that made it.
The metadata travels one path only:

    Export page -> UI export service -> api.export_csv -> run_export_star
    -> _emit_export_manifest -> Artifact.meta

These tests pin the three things that make that safe: the projection is
all-or-nothing and identity-only, the effective source (not merely the active
context) decides whether anything is attached, and the metadata never touches the
CSV-reading path or the manifest schema.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from data_quality_toolkit.adapters.ui.pages import export
from data_quality_toolkit.adapters.ui.services.dataset_activation import make_managed_context
from data_quality_toolkit.adapters.ui.services.dataset_versions import (
    CreationMechanism,
    DatasetFormat,
    DatasetVersionRecord,
    ParentRef,
    RecipeRef,
    new_family_id,
    new_version_id,
)
from data_quality_toolkit.adapters.ui.services.export import _export_csv_to_dir
from data_quality_toolkit.adapters.ui.services.export_alignment import (
    MANAGED_SOURCE_ORIGIN,
    ExportSourceAlignment,
    ExportSourceStatus,
    classify_export_source,
    managed_manifest_metadata,
    normalize_source_binding,
)
from data_quality_toolkit.adapters.ui.services.managed_export_gateway import (
    ManagedExportRefusedError,
    build_verified_managed_export_source,
)
from data_quality_toolkit.adapters.ui.services.managed_trust import (
    commit_trust_root,
    ensure_session_capability,
    make_source_locator,
)
from data_quality_toolkit.adapters.ui.state.context import DatasetContext
from data_quality_toolkit.adapters.ui.state.export_context import get_export_artifact_context
from data_quality_toolkit.adapters.ui.state.keys import (
    DATASET_CONTEXT,
    EXPORT_CSV_PATH,
    EXPORT_OUT_DIR,
    EXPORT_RUN_BTN,
    SRC_SESSION_RUN_ID,
)
from data_quality_toolkit.shared.managed_export_source import (
    MANAGED_FULL_MAX_SOURCE_BYTES,
    VerifiedManagedExportSource,
)

_MOCK_EXPORT = "data_quality_toolkit.adapters.ui.pages.export._export_csv_to_dir"
_CONFIRM_LABEL = "I confirm: write export files to the directory above"

_PRIVATE_DIR = r"C:\Users\example_user\private"
_SOURCE_PATH = _PRIVATE_DIR + r"\sales.csv"
_OTHER_PATH = _PRIVATE_DIR + r"\other.csv"
_OUT_DIR = _PRIVATE_DIR + r"\dist"

_CONTENT_A = "sha256:" + "a" * 64
_ROOT = "sha256:" + "c" * 64

_LIFECYCLE_KEYS = {
    "source_version_id",
    "source_family_id",
    "source_content_id",
    "source_origin",
}


class FakeSt:
    """Streamlit-like recorder with key-backed session state."""

    def __init__(self, session_state: dict[str, Any] | None = None) -> None:
        self.session_state = session_state if session_state is not None else {}
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

    def expander(self, label: str, **kwargs: Any) -> FakeSt:
        self._record("expander", label, **kwargs)
        return self

    def text_input(self, label: str, **kwargs: Any) -> str:
        self._record("text_input", label, **kwargs)
        key = kwargs.get("key")
        if isinstance(key, str) and key in self.text_values:
            return self.text_values[key]
        if label in self.text_values:
            return self.text_values[label]
        if isinstance(key, str):
            return str(self.session_state.get(key, kwargs.get("value", "")))
        return str(kwargs.get("value", ""))

    def checkbox(self, label: str, **kwargs: Any) -> bool:
        self._record("checkbox", label, **kwargs)
        key = kwargs.get("key", label)
        if key in self.checkbox_values:
            return self.checkbox_values[key]
        return bool(kwargs.get("value", False))

    def button(self, label: str, **kwargs: Any) -> bool:
        self._record("button", label, **kwargs)
        key = kwargs.get("key", label)
        return bool(self.button_values.get(key, self.button_values.get(label, False)))

    def rendered_text(self) -> str:
        return " ".join(
            str(value) for _, args, _ in self.calls for value in args if isinstance(value, str)
        )


def _record(**overrides: Any) -> DatasetVersionRecord:
    values: dict[str, Any] = {
        "schema_version": 1,
        "version_id": new_version_id(),
        "family_id": new_family_id(),
        "root_content_id": _ROOT,
        "content_id": _CONTENT_A,
        "dataset_id": "sha1:" + "d" * 40,
        "label": "cleaned v2",
        "file_relative_path": "versions/v1/data.csv",
        "format": DatasetFormat.CSV,
        "size_bytes": 2048,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "created_by": CreationMechanism.PREPROCESS_RECIPE,
    }
    values.update(overrides)
    # A processed version must carry an immediate parent and a recipe. An unmanaged
    # parent maps to parent_version_id=None and the recipe is unread by the export
    # manifest, so these synthetic references keep the invariant without changing
    # any observed metadata.
    if values["created_by"] is CreationMechanism.PREPROCESS_RECIPE:
        values.setdefault("parent", ParentRef(version_id=None, content_id=_ROOT))
        values.setdefault(
            "recipe", RecipeRef(digest="sha256:" + "e" * 64, relative_path="recipes/v1.json")
        )
    return DatasetVersionRecord(**values)


def _managed(source_path: str = _SOURCE_PATH, **overrides: Any) -> DatasetContext:
    return make_managed_context(
        _record(**overrides),
        source_path=source_path,
        display_name="sales.csv",
        size_bytes=2048,
        modified_ns=10,
    )


def _legacy(source_path: str = _SOURCE_PATH) -> DatasetContext:
    return DatasetContext(
        source_path=source_path, display_name="sales.csv", size_bytes=2048, modified_ns=10
    )


def _export_result(**overrides: Any) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_id": "run-p5c-1",
        "dataset_id": "sha1:exported",
        "ts": "2026-07-17T10:00:00Z",
        "export_paths": {"dim_dataset": _OUT_DIR + r"\star\dim_dataset.csv"},
    }
    result.update(overrides)
    return result


def _confirmed_export_st(state: dict[str, Any] | None = None) -> FakeSt:
    st = FakeSt(state if state is not None else {})
    st.text_values[EXPORT_CSV_PATH] = _SOURCE_PATH
    st.text_values[EXPORT_OUT_DIR] = _OUT_DIR
    st.checkbox_values[_CONFIRM_LABEL] = True
    st.button_values[EXPORT_RUN_BTN] = True
    return st


def _run_export(st: FakeSt, result: dict[str, Any] | None, err: str | None = None) -> Any:
    with patch(_MOCK_EXPORT, return_value=(result, err)) as mock_export:
        export._render_export(st)
    return mock_export


# ── A/B. Pure projection ────────────────────────────────────────────────────


def test_managed_alignment_projects_exactly_the_four_admitted_keys() -> None:
    context = _managed()
    alignment = classify_export_source(_SOURCE_PATH, context)

    meta = managed_manifest_metadata(alignment)

    assert meta is not None
    assert set(meta) == _LIFECYCLE_KEYS
    assert meta["source_version_id"] == context.version_id
    assert meta["source_family_id"] == context.family_id
    assert meta["source_content_id"] == context.content_id
    assert meta["source_origin"] == MANAGED_SOURCE_ORIGIN
    assert MANAGED_SOURCE_ORIGIN == "managed_version"


def test_projected_values_are_json_serializable_strings() -> None:
    meta = managed_manifest_metadata(classify_export_source(_SOURCE_PATH, _managed()))

    assert meta is not None
    assert all(isinstance(value, str) for value in meta.values())
    assert json.loads(json.dumps(meta)) == meta


def test_projection_excludes_paths_labels_and_unrelated_identities() -> None:
    context = _managed()
    meta = managed_manifest_metadata(classify_export_source(_SOURCE_PATH, context))

    assert meta is not None
    blob = json.dumps(meta)
    # Nothing host-specific, path-like, or operator-authored may be persisted.
    assert _PRIVATE_DIR not in blob
    assert _SOURCE_PATH not in blob
    assert normalize_source_binding(_SOURCE_PATH) not in blob
    assert "sales.csv" not in blob
    assert "cleaned v2" not in blob
    # Identities that are deliberately not part of the contract.
    root_content_id = context.root_content_id
    assert root_content_id is not None
    assert root_content_id not in blob
    assert "sha1:" not in blob
    for forbidden in (
        "source_path",
        "binding",
        "display_name",
        "root_content_id",
        "parent_version_id",
        "dataset_id",
        "active",
        "run_id",
    ):
        assert forbidden not in set(meta)


def test_legacy_match_projects_no_metadata() -> None:
    assert managed_manifest_metadata(classify_export_source(_SOURCE_PATH, _legacy())) is None


def test_explicit_override_projects_no_metadata() -> None:
    # A managed version is active, but the export uses a different file.
    alignment = classify_export_source(_OTHER_PATH, _managed())
    assert alignment.status is ExportSourceStatus.EXPLICIT_OVERRIDE
    assert managed_manifest_metadata(alignment) is None


def test_no_active_dataset_projects_no_metadata() -> None:
    assert managed_manifest_metadata(classify_export_source(_SOURCE_PATH, None)) is None


def test_incomplete_managed_linkage_projects_nothing_rather_than_partial() -> None:
    # A half-linked export looks authoritative but is unresolvable, so the
    # mapping is omitted entirely rather than emitted with a gap.
    for missing in ("version_id", "family_id", "content_id"):
        fields = {
            "version_id": new_version_id(),
            "family_id": new_family_id(),
            "content_id": _CONTENT_A,
        }
        fields[missing] = ""
        alignment = ExportSourceAlignment(
            status=ExportSourceStatus.ACTIVE_MANAGED,
            display_name="sales.csv",
            binding=normalize_source_binding(_SOURCE_PATH),
            source_present=True,
            **fields,
        )
        assert alignment.may_attach_lifecycle_identity is True
        assert managed_manifest_metadata(alignment) is None, missing


def test_projection_returns_a_fresh_mapping_each_call() -> None:
    alignment = classify_export_source(_SOURCE_PATH, _managed())

    first = managed_manifest_metadata(alignment)
    second = managed_manifest_metadata(alignment)

    assert first == second
    assert first is not second


# ── C. Export page handoff ──────────────────────────────────────────────────


def test_export_page_passes_metadata_for_a_matching_managed_source() -> None:
    context = _managed()
    st = _confirmed_export_st({DATASET_CONTEXT: context})

    mock_export = _run_export(st, _export_result())

    meta = mock_export.call_args.kwargs["artifact_meta"]
    assert meta == {
        "source_version_id": context.version_id,
        "source_family_id": context.family_id,
        "source_content_id": context.content_id,
        "source_origin": MANAGED_SOURCE_ORIGIN,
    }


def test_export_page_passes_no_metadata_for_an_explicit_override() -> None:
    # The active context is managed, but the export's effective source is not it.
    st = _confirmed_export_st({DATASET_CONTEXT: _managed(_PRIVATE_DIR + r"\managed.csv")})

    mock_export = _run_export(st, _export_result())

    assert mock_export.call_args.kwargs["artifact_meta"] is None


def test_export_page_passes_no_metadata_for_a_legacy_source() -> None:
    st = _confirmed_export_st({DATASET_CONTEXT: _legacy()})

    mock_export = _run_export(st, _export_result())

    assert mock_export.call_args.kwargs["artifact_meta"] is None


def test_export_page_passes_no_metadata_without_an_active_dataset() -> None:
    st = _confirmed_export_st()

    mock_export = _run_export(st, _export_result())

    assert mock_export.call_args.kwargs["artifact_meta"] is None


# ── D/E. Service and API propagation ────────────────────────────────────────


def test_ui_service_forwards_metadata_unchanged(tmp_path: Path) -> None:
    meta = {"source_version_id": "v", "source_origin": MANAGED_SOURCE_ORIGIN}

    with patch("data_quality_toolkit.api.export_csv", return_value={"export_paths": {}}) as api:
        _export_csv_to_dir(str(tmp_path / "in.csv"), str(tmp_path / "out"), artifact_meta=meta)

    assert api.call_args.kwargs["artifact_meta"] is meta
    assert api.call_args.kwargs["emit_manifest"] is True


def test_ui_service_without_metadata_still_works(tmp_path: Path) -> None:
    with patch("data_quality_toolkit.api.export_csv", return_value={"export_paths": {}}) as api:
        result, err = _export_csv_to_dir(str(tmp_path / "in.csv"), str(tmp_path / "out"))

    assert err is None
    assert result == {"export_paths": {}}
    assert api.call_args.kwargs["artifact_meta"] is None


def test_api_forwards_metadata_to_the_workflow(tmp_path: Path) -> None:
    from data_quality_toolkit.api import export_csv

    meta = {"source_version_id": "v", "source_origin": MANAGED_SOURCE_ORIGIN}
    mock_return = {"run_id": "r1", "export_paths": {}, "profile": {}, "assessment": {}}

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_export_star",
        return_value=mock_return,
    ) as mock_fn:
        export_csv(tmp_path / "fake.csv", output_dir=str(tmp_path), artifact_meta=meta)

    assert mock_fn.call_args.kwargs["artifact_meta"] is meta


def test_api_forwards_metadata_on_the_null_threshold_path_too(tmp_path: Path) -> None:
    from data_quality_toolkit.api import export_csv

    meta = {"source_origin": MANAGED_SOURCE_ORIGIN}
    mock_return = {"run_id": "r1", "export_paths": {}, "profile": {}, "assessment": {}}

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_export_star",
        return_value=mock_return,
    ) as mock_fn:
        export_csv(
            tmp_path / "fake.csv",
            output_dir=str(tmp_path),
            null_threshold=0.1,
            artifact_meta=meta,
        )

    assert mock_fn.call_args.kwargs["artifact_meta"] is meta
    assert mock_fn.call_args.kwargs["null_threshold"] == 0.1


def test_api_default_passes_no_metadata(tmp_path: Path) -> None:
    from data_quality_toolkit.api import export_csv

    mock_return = {"run_id": "r1", "export_paths": {}, "profile": {}, "assessment": {}}

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.run_export_star",
        return_value=mock_return,
    ) as mock_fn:
        export_csv(tmp_path / "fake.csv", output_dir=str(tmp_path))

    assert mock_fn.call_args.kwargs["artifact_meta"] is None


# ── F. Workflow threading: metadata must never reach the CSV reader ─────────


def test_artifact_meta_is_declared_before_the_csv_read_kwargs() -> None:
    import inspect

    from data_quality_toolkit.application.workflow.pipeline import run_export_star

    params = list(inspect.signature(run_export_star).parameters.values())
    names = [param.name for param in params]
    var_kw_index = next(i for i, p in enumerate(params) if p.kind is p.VAR_KEYWORD)

    # Declared explicitly and earlier than **read_csv_kwargs, so it can never be
    # swept up and handed to load_csv/pandas.read_csv.
    assert "artifact_meta" in names
    assert names.index("artifact_meta") < var_kw_index


def test_metadata_never_enters_load_csv_kwargs(tmp_path: Path) -> None:
    from data_quality_toolkit.application.workflow import pipeline

    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("id,amount\n1,10\n2,20\n", encoding="utf-8")
    meta = {"source_origin": MANAGED_SOURCE_ORIGIN, "source_version_id": "v"}
    seen: dict[str, Any] = {}

    real_load_csv = pipeline.load_csv

    def _spy(path: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return real_load_csv(path, **kwargs)

    with patch.object(pipeline, "load_csv", side_effect=_spy):
        pipeline.run_export_star(
            str(csv_path),
            output_dir=str(tmp_path / "dist"),
            emit_manifest=True,
            artifact_meta=meta,
        )

    assert "artifact_meta" not in seen
    assert not any(key.startswith("source_") for key in seen)


def test_metadata_reaches_only_manifest_emission(tmp_path: Path) -> None:
    from data_quality_toolkit.application.workflow import pipeline

    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("id,amount\n1,10\n", encoding="utf-8")
    meta = {"source_origin": MANAGED_SOURCE_ORIGIN}

    with patch.object(pipeline, "_emit_export_manifest", return_value="x") as emit:
        pipeline.run_export_star(
            str(csv_path),
            output_dir=str(tmp_path / "dist"),
            emit_manifest=True,
            artifact_meta=meta,
        )

    assert emit.call_args.kwargs["artifact_meta"] is meta


# ── F/G. Artifact.meta emission and manifest compatibility ──────────────────


def _export_with_meta(tmp_path: Path, meta: dict[str, object] | None) -> dict[str, Any]:
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("id,amount\n1,10\n2,20\n", encoding="utf-8")
    result, err = _export_csv_to_dir(str(csv_path), str(tmp_path / "dist"), artifact_meta=meta)
    assert err is None, err
    assert result is not None
    manifest_path = Path(result["export_paths"]["manifest"])
    return cast(dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8")))


def _managed_meta() -> dict[str, object]:
    return {
        "source_version_id": "3f1c9a2e-5b6d-4e7f-8a9b-0c1d2e3f4a5b",
        "source_family_id": "8b7a6c5d-4e3f-4a2b-9c8d-7e6f5a4b3c2d",
        "source_content_id": _CONTENT_A,
        "source_origin": MANAGED_SOURCE_ORIGIN,
    }


def test_every_artifact_of_one_export_carries_the_same_metadata(tmp_path: Path) -> None:
    meta = _managed_meta()

    manifest = _export_with_meta(tmp_path, meta)

    artifacts = manifest["artifacts"]
    assert len(artifacts) > 1
    assert all(artifact["meta"] == meta for artifact in artifacts)


def test_each_artifact_receives_its_own_meta_dict(tmp_path: Path) -> None:
    from data_quality_toolkit.application.workflow.pipeline import _emit_export_manifest

    out_dir = tmp_path / "dist"
    (out_dir / "star").mkdir(parents=True)
    paths = {}
    for name in ("dim_dataset", "dim_column"):
        artifact_path = out_dir / "star" / f"{name}.csv"
        artifact_path.write_text("a,b\n1,2\n", encoding="utf-8")
        paths[name] = str(artifact_path)
    source = tmp_path / "sales.csv"
    source.write_text("id\n1\n", encoding="utf-8")
    meta = _managed_meta()

    with patch(
        "data_quality_toolkit.application.workflow.pipeline.build_and_write"
    ) as build_and_write:
        _emit_export_manifest(
            run_id="run-1",
            base_out=out_dir,
            csv_path=str(source),
            prof_rows=1,
            score=1.0,
            paths=paths,
            artifact_meta=meta,
        )

    artifacts = build_and_write.call_args.kwargs["artifacts"]
    assert len(artifacts) == 2
    metas = [artifact.meta for artifact in artifacts]
    assert all(value == meta for value in metas)
    # Distinct objects: no aliasing between artifacts, and none aliases the input.
    assert metas[0] is not metas[1]
    assert all(value is not meta for value in metas)


def test_caller_mapping_is_not_mutated(tmp_path: Path) -> None:
    meta = _managed_meta()
    snapshot = dict(meta)

    _export_with_meta(tmp_path, meta)

    assert meta == snapshot


def test_export_without_metadata_keeps_the_previous_manifest_shape(tmp_path: Path) -> None:
    manifest = _export_with_meta(tmp_path, None)

    assert manifest["artifacts"]
    assert all(artifact["meta"] == {} for artifact in manifest["artifacts"])


def test_generated_manifest_round_trips_through_the_existing_reader(tmp_path: Path) -> None:
    from data_quality_toolkit.lineage.manifest import load_manifest

    meta = _managed_meta()
    csv_path = tmp_path / "sales.csv"
    csv_path.write_text("id,amount\n1,10\n", encoding="utf-8")
    result, err = _export_csv_to_dir(str(csv_path), str(tmp_path / "dist"), artifact_meta=meta)
    assert err is None
    assert result is not None

    manifest_path = Path(result["export_paths"]["manifest"])
    mtime_before = manifest_path.stat().st_mtime_ns
    manifest = load_manifest(manifest_path)

    assert manifest.run_id == result["run_id"]
    assert all(artifact.meta == meta for artifact in manifest.artifacts)
    # Read-only: loading never rewrites the file, and nothing patches it after
    # emission.
    assert manifest_path.stat().st_mtime_ns == mtime_before


def test_old_manifest_without_meta_still_parses(tmp_path: Path) -> None:
    from data_quality_toolkit.lineage.manifest import load_manifest

    # A manifest written before this gate: artifacts carry no meta key at all.
    legacy_manifest = {
        "schema_version": "1.0.0",
        "run_id": "run-old",
        "created_at": "2026-01-01T00:00:00Z",
        "datasets": [],
        "artifacts": [{"kind": "star", "path": "star/dim_dataset.csv", "bytes": 5}],
        "summary": {},
        "gates": {"status": "skipped", "failures": []},
    }
    path = tmp_path / "artifacts.json"
    path.write_text(json.dumps(legacy_manifest), encoding="utf-8")

    manifest = load_manifest(path)

    assert manifest.run_id == "run-old"
    assert manifest.artifacts[0].meta == {}


def test_manifest_metadata_leaks_no_path_or_unrelated_identity(tmp_path: Path) -> None:
    meta = _managed_meta()

    manifest = _export_with_meta(tmp_path, meta)

    for artifact in manifest["artifacts"]:
        blob = json.dumps(artifact["meta"])
        assert str(tmp_path) not in blob
        assert "sha1:" not in blob
        assert set(artifact["meta"]) == _LIFECYCLE_KEYS


def test_override_and_legacy_manifests_contain_no_lifecycle_keys(tmp_path: Path) -> None:
    # Whatever the active context is, an unlinked export projects None, and None
    # must leave the manifest carrying no lifecycle keys at all.
    manifest = _export_with_meta(tmp_path, None)

    for artifact in manifest["artifacts"]:
        assert not _LIFECYCLE_KEYS & set(artifact["meta"])


# ── H. Failure behavior is unchanged ────────────────────────────────────────


def test_failed_export_claims_no_lifecycle_linked_manifest() -> None:
    context = _managed()
    st = _confirmed_export_st({DATASET_CONTEXT: context, SRC_SESSION_RUN_ID: "run-operator"})

    _run_export(st, None, err="disk full")

    from data_quality_toolkit.adapters.ui.state.export_context import get_export_artifact_context
    from data_quality_toolkit.adapters.ui.state.keys import SRC_EXPORT_RUN_ID

    # No success is claimed, and the P5A/P5B contracts are untouched by this flow.
    assert get_export_artifact_context(st.session_state) is None
    assert SRC_EXPORT_RUN_ID not in st.session_state
    assert st.session_state[SRC_SESSION_RUN_ID] == "run-operator"
    assert "Export failed" in st.rendered_text()


def test_managed_export_does_not_disturb_the_session_run_id() -> None:
    st = _confirmed_export_st({DATASET_CONTEXT: _managed(), SRC_SESSION_RUN_ID: "run-operator"})

    _run_export(st, _export_result())

    assert st.session_state[SRC_SESSION_RUN_ID] == "run-operator"


# ── Managed trusted export lifecycle metadata ───────────────────────────────

_MOCK_MANAGED_EXPORT = "data_quality_toolkit.adapters.ui.pages.export._export_managed_source_to_dir"
_MANAGED_ABS = _PRIVATE_DIR + r"\preprocessed\customers.csv"


def _trusted_export_state(*, large: bool = False, size: int = 2048) -> tuple[dict[str, Any], Any]:
    state: dict[str, Any] = {}
    capability = ensure_session_capability(state)
    root = commit_trust_root(
        state,
        capability,
        version_id=new_version_id(),
        family_id=new_family_id(),
        content_id=_CONTENT_A,
        root_content_id=_ROOT,
        parent_version_id=None,
        version_label="cleaned v2",
        locator=make_source_locator(
            display_name="customers.csv",
            relative_posix="preprocessed/customers.csv",
            absolute_path=_MANAGED_ABS,
        ),
        size_bytes=size,
        modified_ns=10,
        large_file_mode=large,
    )
    return state, root


def _run_managed_export(st: FakeSt, result: dict[str, Any] | None) -> Any:
    with patch(_MOCK_MANAGED_EXPORT, return_value=result) as mock_managed:
        export._render_export(st)
    return mock_managed


def test_trusted_managed_export_uses_the_managed_sibling() -> None:
    state, _root = _trusted_export_state()
    st = _confirmed_export_st(state)

    with patch(_MOCK_EXPORT) as legacy:
        mock_managed = _run_managed_export(st, _export_result())

    legacy.assert_not_called()
    assert mock_managed.call_count == 1


def test_trusted_managed_export_passes_provenance_whole() -> None:
    state, root = _trusted_export_state()
    st = _confirmed_export_st(state)

    mock_managed = _run_managed_export(st, _export_result())

    source = mock_managed.call_args.args[0]
    assert isinstance(source, VerifiedManagedExportSource)
    assert source.version_id == root.version_id
    assert source.content_id == root.content_id
    assert source.family_id == root.family_id
    # Provenance is one object; nothing is decomposed into extra arguments.
    assert len(mock_managed.call_args.args) == 2
    assert mock_managed.call_args.kwargs == {}


def test_manual_csv_path_cannot_redirect_a_trusted_managed_export() -> None:
    state, root = _trusted_export_state()
    st = _confirmed_export_st(state)
    st.text_values[EXPORT_CSV_PATH] = _OTHER_PATH  # operator override attempt

    mock_managed = _run_managed_export(st, _export_result())

    source = mock_managed.call_args.args[0]
    assert source.source_path == root.locator.absolute_path
    assert source.source_path != _OTHER_PATH


def test_trusted_managed_export_alignment_is_active_managed() -> None:
    state, root = _trusted_export_state()
    st = _confirmed_export_st(state)
    st.text_values[EXPORT_CSV_PATH] = _OTHER_PATH

    _run_managed_export(st, _export_result())

    stored = get_export_artifact_context(st.session_state)
    assert stored is not None
    assert stored.source_version_id == root.version_id
    assert stored.source_content_id == root.content_id


def test_managed_large_export_is_refused_without_unmanaged_fallback() -> None:
    state, _root = _trusted_export_state(large=True)
    st = _confirmed_export_st(state)

    with (
        patch(_MOCK_EXPORT) as legacy,
        patch(_MOCK_MANAGED_EXPORT) as managed,
    ):
        export._render_export(st)

    legacy.assert_not_called()
    managed.assert_not_called()
    assert any("refused" in str(a).lower() for _, args, _ in st.calls for a in args)


def test_managed_oversize_export_is_refused_without_unmanaged_fallback() -> None:
    state, _root = _trusted_export_state(size=MANAGED_FULL_MAX_SOURCE_BYTES + 1)
    st = _confirmed_export_st(state)

    with (
        patch(_MOCK_EXPORT) as legacy,
        patch(_MOCK_MANAGED_EXPORT) as managed,
    ):
        export._render_export(st)

    legacy.assert_not_called()
    managed.assert_not_called()


def test_managed_export_refusal_message_is_privacy_safe() -> None:
    state, _root = _trusted_export_state(large=True)
    st = _confirmed_export_st(state)

    with patch(_MOCK_EXPORT), patch(_MOCK_MANAGED_EXPORT):
        export._render_export(st)

    text = " ".join(str(a) for _, args, _ in st.calls for a in args if isinstance(a, str))
    assert _MANAGED_ABS not in text
    assert _PRIVATE_DIR not in text


def test_managed_export_failure_never_falls_back_to_unmanaged() -> None:
    state, _root = _trusted_export_state()
    st = _confirmed_export_st(state)

    with (
        patch(_MOCK_EXPORT) as legacy,
        patch(_MOCK_MANAGED_EXPORT, side_effect=OSError("disk full")),
    ):
        export._render_export(st)

    legacy.assert_not_called()
    assert get_export_artifact_context(st.session_state) is None


def test_untrusted_managed_mirror_keeps_unchanged_legacy_manifest_behavior() -> None:
    """An untrusted managed mirror can never mint verified provenance...

    ...so it keeps exactly the legacy unmanaged treatment, including the
    accepted managed-context lifecycle metadata projection.
    """
    context = _managed()
    st = _confirmed_export_st({DATASET_CONTEXT: context})

    with patch(_MOCK_MANAGED_EXPORT) as managed:
        mock_export = _run_export(st, _export_result())

    managed.assert_not_called()  # trusted managed path never engages
    meta = mock_export.call_args.kwargs["artifact_meta"]
    assert meta is not None
    assert set(meta) == _LIFECYCLE_KEYS
    assert meta["source_version_id"] == context.version_id


def test_untrusted_mirror_cannot_mint_verified_provenance() -> None:
    state: dict[str, Any] = {DATASET_CONTEXT: _managed()}

    with pytest.raises(ManagedExportRefusedError) as excinfo:
        build_verified_managed_export_source(state)

    assert excinfo.value.reason_code == "MANAGED_MIRROR_WITHOUT_TRUST"
