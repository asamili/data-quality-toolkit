"""Unit tests for the shared managed-export provenance contract.

Proves immutability, field validation, privacy of the public surface, the
exact FULL source-size boundary, and that the shared module is importable
without any UI, Streamlit, or pandas dependency.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import uuid

import pytest

from data_quality_toolkit.shared import managed_export_source as module
from data_quality_toolkit.shared.managed_export_source import (
    MANAGED_FULL_MAX_SOURCE_BYTES,
    VerifiedManagedExportSource,
)

_ABS = "C:\\workspace\\versions\\v1\\data.csv"


def _source(**overrides: object) -> VerifiedManagedExportSource:
    values: dict[str, object] = {
        "version_id": str(uuid.uuid4()),
        "family_id": str(uuid.uuid4()),
        "content_id": "sha256:" + "a" * 64,
        "root_content_id": "sha256:" + "b" * 64,
        "parent_version_id": None,
        "version_label": "cleaned v2",
        "display_name": "data.csv",
        "relative_posix": "versions/v1/data.csv",
        "size_bytes": 2048,
        "modified_ns": 10,
        "large_file_mode": False,
        "source_path": _ABS,
    }
    values.update(overrides)
    return VerifiedManagedExportSource(**values)  # type: ignore[arg-type]


# --- A. Immutability ----------------------------------------------------------


def test_source_is_frozen() -> None:
    source = _source()
    with pytest.raises(dataclasses.FrozenInstanceError):
        source.version_id = "tampered"  # type: ignore[misc]


def test_source_is_slotted() -> None:
    source = _source()
    with pytest.raises((AttributeError, TypeError)):
        source.extra = "smuggled"  # type: ignore[attr-defined]


def test_provenance_is_one_value_not_decomposed() -> None:
    # The contract is a single frozen dataclass carrying the complete managed
    # provenance; every managed sibling accepts exactly one of these.
    field_names = {f.name for f in dataclasses.fields(VerifiedManagedExportSource)}
    assert {
        "version_id",
        "family_id",
        "content_id",
        "root_content_id",
        "version_label",
        "size_bytes",
        "large_file_mode",
        "source_path",
    } <= field_names


# --- B. Field validation --------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    ["version_id", "family_id", "content_id", "root_content_id", "version_label"],
)
def test_blank_identity_fields_are_refused(field_name: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _source(**{field_name: "   "})


def test_pathlike_display_name_is_refused() -> None:
    with pytest.raises(ValueError, match="bare file name"):
        _source(display_name="C:\\data.csv")
    with pytest.raises(ValueError, match="bare file name"):
        _source(display_name="versions/data.csv")


def test_absolute_relative_posix_is_refused() -> None:
    with pytest.raises(ValueError, match="workspace-relative"):
        _source(relative_posix="/abs/data.csv")
    with pytest.raises(ValueError, match="workspace-relative"):
        _source(relative_posix="C:/abs/data.csv")
    with pytest.raises(ValueError, match="workspace-relative"):
        _source(relative_posix="versions\\v1\\data.csv")


def test_negative_size_is_refused() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        _source(size_bytes=-1)


def test_blank_machine_path_is_refused() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        _source(source_path="  ")


# --- C. Size boundary --------------------------------------------------------------


def test_full_source_exactly_at_boundary_is_permitted() -> None:
    source = _source(size_bytes=MANAGED_FULL_MAX_SOURCE_BYTES)
    assert source.size_bytes == 134_217_728


def test_full_source_above_boundary_is_refused() -> None:
    with pytest.raises(ValueError, match="maximum permitted size"):
        _source(size_bytes=MANAGED_FULL_MAX_SOURCE_BYTES + 1)


def test_large_mode_source_may_exceed_boundary_at_construction() -> None:
    # LARGE sources are refused at load/export dispatch, not at provenance
    # construction; the contract still records their true size.
    source = _source(size_bytes=MANAGED_FULL_MAX_SOURCE_BYTES + 1, large_file_mode=True)
    assert source.large_file_mode is True


def test_boundary_constant_value_is_exact() -> None:
    assert MANAGED_FULL_MAX_SOURCE_BYTES == 134_217_728


# --- D. Privacy ------------------------------------------------------------------------


def test_repr_hides_machine_path() -> None:
    source = _source()
    for text in (repr(source), str(source)):
        assert _ABS not in text
        assert "C:\\" not in text
    assert source.source_path == _ABS


def test_validation_errors_never_echo_the_machine_path() -> None:
    with pytest.raises(ValueError) as excinfo:
        _source(version_id="")
    assert _ABS not in str(excinfo.value)


# --- E. UI independence -------------------------------------------------------------------


def test_module_imports_only_the_standard_library() -> None:
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module.split(".")[0])
    # Every name here is a Python standard-library module. The managed-source
    # verification policy legitimately needs hashlib (canonical content id),
    # os (case-insensitive path comparison), and stat (regular-file check).
    assert imported <= {"__future__", "dataclasses", "hashlib", "os", "pathlib", "stat"}


def test_module_has_no_ui_streamlit_or_pandas_names() -> None:
    for banned in ("streamlit", "pandas", "adapters"):
        assert banned not in module.__dict__
