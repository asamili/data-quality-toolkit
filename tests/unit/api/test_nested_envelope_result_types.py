"""DQT-UX-G8C2G: nested envelope result contracts for profile/assess/export.

Proves the 11 nested TypedDicts (CsvMeta, CsvProfileColumn, CsvProfile,
CsvProfileCompact, CsvAssessmentIssue, CsvAssessment, CsvStarExport,
CsvExportPaths, ProfileCsvResult, AssessCsvResult, ExportCsvResult) are
importable from ``shared.result_types``, the ``data_quality_toolkit.api`` seam,
and the package root; are the same object through all three paths; are listed in
each public ``__all__``; and carry exactly the required/optional keys from the
accepted G8C2F design.

G8C2H wires the three public wrappers (``profile_csv``, ``assess_csv``,
``export_csv``) to these contracts: each now carries its envelope return
annotation and a static-only ``cast(...)`` over the unchanged returned expression.
Runtime behavior is unchanged — the wrappers still return the same plain dicts.
"""

from __future__ import annotations

import importlib
import inspect
import re
import typing
from typing import Any, get_type_hints

import pytest


def _required_optional(cls: Any) -> tuple[set[str], set[str]]:
    """Resolve a TypedDict's required/optional key sets reliably.

    ``__required_keys__`` / ``__optional_keys__`` do not see per-key
    ``NotRequired`` under ``from __future__ import annotations`` (PEP 563), so we
    inspect resolved hints with ``include_extras=True`` instead. A ``total=False``
    class makes every key optional.
    """
    hints = get_type_hints(cls, include_extras=True)
    keys = set(hints)
    if cls.__total__ is False:
        return set(), keys
    optional = {k for k, v in hints.items() if typing.get_origin(v) is typing.NotRequired}
    return keys - optional, optional


_NESTED_TYPES = [
    "CsvMeta",
    "CsvProfileColumn",
    "CsvProfile",
    "CsvProfileCompact",
    "CsvAssessmentIssue",
    "CsvAssessment",
    "CsvStarExport",
    "CsvExportPaths",
    "ProfileCsvResult",
    "AssessCsvResult",
    "ExportCsvResult",
]

# (required keys, optional keys) per the G8C2F design.
_EXPECTED: dict[str, tuple[set[str], set[str]]] = {
    "CsvMeta": (
        {
            "dataset_id",
            "source_path",
            "file_size_bytes",
            "modified_ts",
            "sample_applied",
            "sample_size",
        },
        {"rows", "cols", "chunksize"},
    ),
    "CsvProfileColumn": (
        {"name", "dtype", "nulls"},
        {"unique", "min", "max"},
    ),
    "CsvProfile": (
        {"rows", "cols", "memory_mb", "columns"},
        set(),
    ),
    "CsvProfileCompact": (
        {"rows", "cols", "memory_mb"},
        set(),
    ),
    "CsvAssessmentIssue": (
        set(),
        {"type", "column", "pct", "severity", "category", "message"},
    ),
    "CsvAssessment": (
        {"run_id", "dataset_id", "ts", "score", "completeness_score", "issues"},
        {"quality_score", "assessment_mode", "approximate", "unsupported_rules"},
    ),
    "CsvStarExport": (
        {"tables", "rows"},
        set(),
    ),
    "CsvExportPaths": (
        {
            "dim_dataset",
            "dim_column",
            "fact_profile_runs",
            "fact_quality_metrics",
            "fact_issues",
            "relationships",
            "quality_report",
            "quality_history",
        },
        {"manifest"},
    ),
    "ProfileCsvResult": (
        {"run_id", "dataset_id", "ts", "meta", "profile"},
        {"approximate", "unsupported_metrics"},
    ),
    "AssessCsvResult": (
        {"run_id", "dataset_id", "ts", "duration_secs", "meta", "profile", "assessment"},
        {"approximate"},
    ),
    "ExportCsvResult": (
        {
            "run_id",
            "dataset_id",
            "ts",
            "duration_secs",
            "meta",
            "profile",
            "assessment",
            "star",
            "export_paths",
        },
        set(),
    ),
}


# --------------------------------------------------------------------------
# Export-surface checks: importable + in __all__ from all three paths.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", _NESTED_TYPES)
def test_nested_type_importable_from_shared(name: str) -> None:
    mod = importlib.import_module("data_quality_toolkit.shared.result_types")
    assert hasattr(mod, name), f"{name} missing from shared.result_types"
    assert name in mod.__all__, f"{name} missing from shared.result_types.__all__"


@pytest.mark.parametrize("name", _NESTED_TYPES)
def test_nested_type_importable_from_api_seam(name: str) -> None:
    api = importlib.import_module("data_quality_toolkit.api")
    assert hasattr(api, name), f"{name} missing from data_quality_toolkit.api"
    assert name in api.__all__, f"{name} missing from data_quality_toolkit.api.__all__"


@pytest.mark.parametrize("name", _NESTED_TYPES)
def test_nested_type_importable_from_root(name: str) -> None:
    root = importlib.import_module("data_quality_toolkit")
    assert hasattr(root, name), f"{name} missing from data_quality_toolkit"
    assert name in root.__all__, f"{name} missing from data_quality_toolkit.__all__"


@pytest.mark.parametrize("name", _NESTED_TYPES)
def test_nested_type_same_object_from_all_paths(name: str) -> None:
    root = importlib.import_module("data_quality_toolkit")
    api = importlib.import_module("data_quality_toolkit.api")
    shared = importlib.import_module("data_quality_toolkit.shared.result_types")
    assert getattr(root, name) is getattr(api, name) is getattr(shared, name)


# --------------------------------------------------------------------------
# Exact required/optional key contracts.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", _NESTED_TYPES)
def test_nested_type_required_keys(name: str) -> None:
    mod = importlib.import_module("data_quality_toolkit.shared.result_types")
    cls = getattr(mod, name)
    exp_required, exp_optional = _EXPECTED[name]
    required, optional = _required_optional(cls)
    assert required == exp_required
    assert optional == exp_optional
    assert set(cls.__annotations__) == exp_required | exp_optional


# --------------------------------------------------------------------------
# Specific type pins.
# --------------------------------------------------------------------------
def test_assessment_mode_is_literal_chunked() -> None:
    from data_quality_toolkit.shared.result_types import CsvAssessment

    hints = get_type_hints(CsvAssessment)
    mode = hints["assessment_mode"]
    assert typing.get_origin(mode) is typing.Literal
    assert typing.get_args(mode) == ("chunked",)


@pytest.mark.parametrize("cls_name", ["CsvProfile", "CsvProfileCompact"])
def test_memory_mb_is_float_or_none(cls_name: str) -> None:
    import types as _types

    mod = importlib.import_module("data_quality_toolkit.shared.result_types")
    cls = getattr(mod, cls_name)
    hints = get_type_hints(cls)
    memory_mb = hints["memory_mb"]
    assert typing.get_origin(memory_mb) in (typing.Union, getattr(_types, "UnionType", None))
    assert set(typing.get_args(memory_mb)) == {float, type(None)}


def test_export_paths_manifest_is_notrequired() -> None:
    from data_quality_toolkit.shared.result_types import CsvExportPaths

    required, optional = _required_optional(CsvExportPaths)
    assert "manifest" in optional
    assert "manifest" not in required


def test_profile_result_chunked_keys_notrequired() -> None:
    from data_quality_toolkit.shared.result_types import ProfileCsvResult

    required, optional = _required_optional(ProfileCsvResult)
    assert {"approximate", "unsupported_metrics"} <= optional
    assert required == {"run_id", "dataset_id", "ts", "meta", "profile"}


def test_assess_result_chunked_key_notrequired() -> None:
    from data_quality_toolkit.shared.result_types import AssessCsvResult

    required, optional = _required_optional(AssessCsvResult)
    assert "approximate" in optional
    assert "approximate" not in required


# --------------------------------------------------------------------------
# G8C2H: the three wrappers are now annotated with their envelope contracts and
# use a static-only cast over the unchanged returned expression.
# --------------------------------------------------------------------------
_WRAPPER_CONTRACT = {
    "profile_csv": "ProfileCsvResult",
    "assess_csv": "AssessCsvResult",
    "export_csv": "ExportCsvResult",
}


@pytest.mark.parametrize("fn_name, contract", list(_WRAPPER_CONTRACT.items()))
def test_wrapper_return_annotation_is_contract(fn_name: str, contract: str) -> None:
    api = importlib.import_module("data_quality_toolkit.api")
    fn = getattr(api, fn_name)
    # `from __future__ import annotations` keeps annotations as strings.
    assert fn.__annotations__["return"] == contract


@pytest.mark.parametrize("fn_name, contract", list(_WRAPPER_CONTRACT.items()))
def test_wrapper_return_annotation_resolves(fn_name: str, contract: str) -> None:
    # Robust inspection: the string annotation resolves to the exact exported
    # TypedDict object, not just a matching name.
    api = importlib.import_module("data_quality_toolkit.api")
    fn = getattr(api, fn_name)
    resolved = get_type_hints(fn)["return"]
    assert resolved is getattr(api, contract)


@pytest.mark.parametrize("fn_name, contract", list(_WRAPPER_CONTRACT.items()))
def test_wrapper_uses_cast_pattern(fn_name: str, contract: str) -> None:
    # Mirrors the project's existing cast(...) style for contracted wrappers.
    api = importlib.import_module("data_quality_toolkit.api")
    src = inspect.getsource(getattr(api, fn_name))
    # ``cast(`` may wrap across lines for the longer calls, so match flexibly.
    assert re.search(rf"cast\(\s*{contract}\s*,", src)


def test_wrappers_remain_public_exports() -> None:
    # No public export churn: the contracts and wrappers stay on the seam and
    # resolve to the same object from root, api, and shared.
    root = importlib.import_module("data_quality_toolkit")
    api = importlib.import_module("data_quality_toolkit.api")
    shared = importlib.import_module("data_quality_toolkit.shared.result_types")
    for contract in _WRAPPER_CONTRACT.values():
        assert contract in api.__all__
        assert getattr(root, contract) is getattr(api, contract) is getattr(shared, contract)
    for fn_name in _WRAPPER_CONTRACT:
        assert fn_name in api.__all__
