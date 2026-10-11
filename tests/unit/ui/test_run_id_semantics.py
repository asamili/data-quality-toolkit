"""Repository contract tests for session-run vs export-run identity (gate P5B).

One ambiguous ``src_run_id`` key used to carry two unrelated concepts: the name of
a workflow folder under Sessions Root, and the identifier of an Export execution.
Two writers shared one slot, so Export could overwrite the folder identity a
session lookup depended on.

These tests pin the separation itself — that the keys are distinct, that the old
ambiguous names are gone from runtime code, and that no helper accepts either
kind of run ID. Per-page behavior is covered by the page test modules.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from data_quality_toolkit.adapters.ui.components import source_context, source_hub
from data_quality_toolkit.adapters.ui.state import keys

_UI_ROOT = pathlib.Path(source_context.__file__).resolve().parents[1]
_SRC_ROOT = _UI_ROOT.parents[2]

# Runtime modules this gate migrated. Each previously referenced the ambiguous key
# or helper directly.
_AFFECTED_RUNTIME_FILES = (
    "adapters/ui/state/keys.py",
    "adapters/ui/components/source_context.py",
    "adapters/ui/components/source_hub.py",
    "adapters/ui/pages/export.py",
    "adapters/ui/pages/pipeline_runner.py",
    "adapters/ui/pages/artifact_center.py",
    "adapters/ui/pages/manifest_viewer.py",
    "adapters/ui/pages/run_history.py",
)

_REMOVED_NAMES = ("SRC_RUN_ID", "PIPE_RUN_ID", "render_run_id_input", "RUN_ID_HELP")


def _references(name: str, source: str) -> bool:
    """Whether ``source`` names ``name`` as a whole identifier.

    Word-bounded on purpose: a plain substring test would report the replacement
    ``SESSION_RUN_ID_HELP`` as a surviving ``RUN_ID_HELP``, which would make this
    contract fail on correct code and pass only if the rename were abandoned.
    """
    return re.search(rf"\b{re.escape(name)}\b", source) is not None


def _runtime_sources() -> list[tuple[str, str]]:
    return [
        (name, (_SRC_ROOT / "data_quality_toolkit" / name).read_text(encoding="utf-8"))
        for name in _AFFECTED_RUNTIME_FILES
    ]


def _all_ui_python_files() -> list[pathlib.Path]:
    return sorted(p for p in _UI_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


# ── State-key contract ──────────────────────────────────────────────────────


def test_session_and_export_run_id_keys_are_distinct() -> None:
    assert keys.SRC_SESSION_RUN_ID == "src_session_run_id"
    assert keys.SRC_EXPORT_RUN_ID == "src_export_run_id"
    assert keys.SRC_SESSION_RUN_ID != keys.SRC_EXPORT_RUN_ID


def test_ambiguous_and_unused_run_id_keys_are_gone() -> None:
    # A clean rename, not an alias: nothing may resurrect the ambiguous key.
    assert not hasattr(keys, "SRC_RUN_ID")
    # PIPE_RUN_ID had exactly one repository occurrence — its own definition.
    assert not hasattr(keys, "PIPE_RUN_ID")


def test_no_key_still_maps_to_the_old_ambiguous_value() -> None:
    values = {
        name: value
        for name, value in vars(keys).items()
        if name.isupper() and isinstance(value, str)
    }
    assert "src_run_id" not in values.values()
    assert "pipe_run_id" not in values.values()


def test_export_run_id_is_not_dataset_derived_state() -> None:
    # Export evidence is historical: it survives a dataset switch rather than
    # being invalidated with dataset-derived state.
    assert keys.SRC_EXPORT_RUN_ID not in keys.DATASET_DERIVED_STATE_KEYS
    assert keys.SRC_SESSION_RUN_ID not in keys.DATASET_DERIVED_STATE_KEYS


# ── Repository contract: the old names are gone from runtime ────────────────


@pytest.mark.parametrize("name", _REMOVED_NAMES)
def test_removed_name_is_absent_from_every_affected_runtime_file(name: str) -> None:
    offenders = [path for path, source in _runtime_sources() if _references(name, source)]
    assert offenders == [], f"{name} still referenced by: {offenders}"


@pytest.mark.parametrize("name", _REMOVED_NAMES)
def test_removed_name_is_absent_from_the_whole_ui_package(name: str) -> None:
    # Broader than the migrated set: proves no other UI module quietly kept a
    # reference that would have failed at import time.
    offenders = [
        str(path.relative_to(_UI_ROOT))
        for path in _all_ui_python_files()
        if _references(name, path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"{name} still referenced by: {offenders}"


def test_affected_runtime_files_were_actually_scanned() -> None:
    # Guards the contract tests above from silently passing on empty input.
    sources = _runtime_sources()
    assert len(sources) == len(_AFFECTED_RUNTIME_FILES)
    assert all(source.strip() for _, source in sources)


# ── Shared helper contract ──────────────────────────────────────────────────


def test_session_run_helper_exists_and_the_ambiguous_one_does_not() -> None:
    assert callable(source_context.render_session_run_id_input)
    assert not hasattr(source_context, "render_run_id_input")
    assert not hasattr(source_context, "RUN_ID_HELP")


def test_session_run_helper_takes_no_key_parameter() -> None:
    # A helper that accepted a key could be pointed at either run ID, which is
    # exactly the ambiguity this gate removes.
    signature = ast.parse(pathlib.Path(source_context.__file__).read_text(encoding="utf-8"))
    functions = {
        node.name: node for node in ast.walk(signature) if isinstance(node, ast.FunctionDef)
    }
    render = functions["render_session_run_id_input"]
    arg_names = [arg.arg for arg in render.args.args]
    assert arg_names == ["st"]
    assert render.args.kwonlyargs == []


def test_session_run_helper_binds_only_the_session_key() -> None:
    source = pathlib.Path(source_context.__file__).read_text(encoding="utf-8")
    start = source.index("def render_session_run_id_input")
    end = source.index("def export_run_id_evidence")
    body = source[start:end]
    assert "SRC_SESSION_RUN_ID" in body
    assert "SRC_EXPORT_RUN_ID" not in body


def test_export_run_evidence_accessor_binds_only_the_export_key() -> None:
    source = pathlib.Path(source_context.__file__).read_text(encoding="utf-8")
    start = source.index("def export_run_id_evidence")
    end = source.index("def render_dataset_id_input")
    body = source[start:end]
    assert "SRC_EXPORT_RUN_ID" in body
    assert "SRC_SESSION_RUN_ID" not in body


# ── Source Hub field contract ───────────────────────────────────────────────


def test_source_hub_exposes_one_session_run_field_and_no_export_run_field() -> None:
    fields = {field.key: field for field in source_hub.get_source_hub_fields()}
    assert keys.SRC_SESSION_RUN_ID in fields
    # The export-run ID is produced, never typed, so it has no Source Hub input.
    assert keys.SRC_EXPORT_RUN_ID not in fields

    session_field = fields[keys.SRC_SESSION_RUN_ID]
    assert session_field.label == "Session Run ID"
    assert "Sessions Root" in session_field.help


def test_source_hub_field_renderers_never_target_the_export_run_key() -> None:
    renderers = source_hub._FIELD_RENDERERS
    assert renderers[keys.SRC_SESSION_RUN_ID] is source_context.render_session_run_id_input
    assert keys.SRC_EXPORT_RUN_ID not in renderers


def test_workspace_defaults_seed_neither_run_id() -> None:
    # A run ID is never derivable from a Workspace Root path.
    defaults = source_hub.derive_workspace_defaults(r"C:\ws")
    assert keys.SRC_SESSION_RUN_ID not in defaults
    assert keys.SRC_EXPORT_RUN_ID not in defaults
